# Klume Platform — Post-Mortem / Registro de Incidentes e Débito Técnico

Histórico de incidentes reais, decisões operacionais transitórias e limpeza de
débito técnico. **Não é documento de arquitetura** — o padrão técnico
resultante de cada incidente (quando existe) é documentado em
`docs/ARQUITETURA.md`; aqui fica só o "o que aconteceu e por quê", pra
referência futura e pra não repetir o mesmo erro.

Uso interno — não compartilhar com terceiros/parceiros no formato atual (tem
histórico de erro operacional e nomenclatura interna que não precisa sair
daqui).

---

## Incidente: linhas órfãs em upload de teste

Um upload de teste (arquivo de ano de fabricação 1958, usado justamente por
ser um caso extremo de volume baixo) deixou 30 linhas órfãs no Bronze: o
`INSERT` no banco principal teve sucesso, mas a etapa seguinte (gravação
dual no S3) falhou silenciosamente porque a credencial AWS não estava
configurada no ambiente de produção do app — o app rodava, a página não
dava erro visível, só a gravação no S3 não acontecia.

**Causa raiz**: nenhuma verificação de idempotência antes do insert, e falha
numa etapa (S3) não bloqueava nem sinalizava a etapa anterior (banco) já ter
sido concluída. Uma reexecução do mesmo arquivo teria duplicado as linhas em
vez de só completar o que faltou.

**Correção, já em produção** (o padrão técnico resultante está documentado em
`docs/ARQUITETURA.md`, seção de ingestão): tabela de controle registra o hash
do arquivo assim que o insert principal termina, antes de tentar a etapa
seguinte — um arquivo com hash já visto é bloqueado antes de tocar qualquer
tabela, e falha na etapa seguinte fica registrada como incompleta em vez de
mascarada. Validação de schema (colunas obrigatórias presentes, formato bate
com a referência conhecida) também foi adicionada nesse momento — antes,
coluna faltando virava `NULL` silencioso.

## Ingestão histórica via cliente SQL manual

Os anos históricos de Bronze (DENATRAN) foram carregados originalmente via
cliente SQL direto (DBeaver), não por pipeline programática — prática do
estágio inicial do projeto, quando o volume de carga era baixo e a
prioridade era ter dado disponível rápido pra começar a modelar o Silver/
Gold. Cobertura de anos é irregular como resultado direto disso (vários anos
vazios ou parciais) — não é perda de dado, é histórico de carga nunca ter
sido feita de forma sistemática pra todos os anos.

**Status**: em migração pra pipeline programática (mesmo padrão já usado
pro upload corrente via app) — não uma prioridade imediata, já que o volume
de anos históricos restantes é conhecido e finito.

## Restrições de plano de hospedagem — histórico

Duas restrições reais enfrentadas em determinado momento do projeto, ambas
geridas como decisão de custo/quota, não como limitação estrutural
permanente:

- **Armazenamento do banco principal aproximando do teto do tier gratuito**
  — motivou a estratégia de reter dado bruto de baixa frequência de acesso
  (histórico de anos antigos de Bronze) em Parquet fora do banco principal,
  em vez de manter tudo no tier de armazenamento ativo. Essa estratégia virou
  o padrão de arquitetura permanente (retenção híbrida), documentado como tal
  em `docs/ARQUITETURA.md` — a causa original (teto de tier) não precisa se
  repetir pra o padrão continuar fazendo sentido.
- **App de consumo interno hospedado em tier com restrição de autenticação
  por lista de e-mail** — aceitável enquanto o uso é interno/poucos
  usuários; vira bloqueador quando alguém fora da lista precisar de acesso
  direto. Gatilho de revisão: antes de qualquer usuário externo precisar
  logar diretamente no app (ver `docs/architecture-roadmap.md`).

## Mascaramento de CPF em `silver.veiculos.identificacao_faturado` (2026-09-09)

Ao revisar o dicionário de dados recém-criado, achado real de governança de
dado pessoal: quando `tipo_faturado = 'CPF'` (pessoa física), a coluna
`identificacao_faturado` guardava o número do CPF em texto puro, sem
nenhuma máscara — confirmado direto no banco (`~3.018` linhas, `~1.640`
delas com os 11 dígitos de um CPF real; o resto tem sujeira de formatação,
mesmo padrão de bug já corrigido no CNPJ). CPF é dado pessoal sob a LGPD, e
a coluna não tinha nenhum uso downstream — nada em Gold ou no app lê
`identificacao_faturado` diretamente, só a coluna derivada
`cnpj_basico_faturado` (que já só existe pro ramo `CNPJ`).

**Correção**: `silver/normalizers/denatran.py` agora só passa o valor bruto
de `identificacao_faturado` quando `tipo_faturado = 'CNPJ'` — qualquer outro
valor (`CPF`, `Desconhecido`, `Outros`) vira `NULL` na transformação
Bronze → Silver. `Desconhecido`/`Outros` mascarados por precaução também,
já que não dá pra confirmar que não escondem um CPF classificado errado.
Testes de `silver/tests/test_denatran_normalizer.py` confirmam que a
extração de `cnpj_basico_faturado` (ramo CNPJ) não foi afetada. Efetivo a
partir do próximo rebuild do Silver — dado histórico já persistido em
`silver.veiculos` só é corrigido quando essa tabela for reconstruída de
novo a partir do Bronze.

## Limpeza de débito técnico — tabelas e bancos órfãos

Lista de itens de limpeza identificados e seu status, mantida aqui em vez de
em `docs/ARQUITETURA.md` porque nomear schema/tabela específico de um
experimento abandonado é ruído de governança interna, não decisão de
arquitetura.

**Já removidos** (confirmado ausente do catálogo em 2026-09-09):
- Três tabelas de um experimento de integração FIPE abandonado (colunas
  100% nulas em toda a extensão, confirmado por contagem direta antes de
  remover).
- Um dump CSV bruto redundante (versão já parseada existia em paralelo,
  mesma contagem de linha, confirmado idêntico antes de remover).
- Um import parcial abandonado de um domínio já coberto pela versão completa
  parseada.
- Um backup de segurança pré-redesenho do Gold, mantido até o redesenho
  (star schema) ser exaustivamente testado (determinismo de build duplo,
  integridade referencial) — testes passaram, backup removido.

**Removido hoje (2026-09-09), com backup verificado antes**: as três
tabelas brutas de CNPJ que alimentavam o enriquecimento de empresa no Gold
(ver `docs/ARQUITETURA.md`) — juntas somavam a maior fatia do tamanho total
do banco principal. Exportadas como Parquet pra um bucket de armazenamento
frio próprio, contagem de linha exata verificada igual entre origem e
destino antes de qualquer exclusão, só então removidas do banco principal.
Recuperáveis via leitura direta do Parquet se o enriquecimento de empresa
precisar reprocessar a fonte no futuro.

**Ainda pendente, não confirmado com o usuário**: alguns bancos de teste
órfãos, criados num momento anterior do projeto, sem relação com o schema
real em uso hoje — candidatos seguros a remover, aguardando confirmação
antes de agir (mesmo padrão de cautela aplicado às remoções acima: nunca
apagar sem verificar primeiro).

## Migração: surrogate key sequencial → hash determinístico (2026-09-09)

Uma revisão de arquitetura identificou risco real (não hipotético) nas 3
chaves surrogate geradas por `ROW_NUMBER() OVER (ORDER BY <chave de
negócio>)` (`dim_veiculo_observado.veiculo_key`,
`dim_veiculo_atual.veiculo_atual_key`, `dim_empresa.empresa_key`): uma
entidade nova que ordena antes de uma existente desloca toda chave
depois dela a cada rebuild, corrompendo silenciosamente qualquer FK física
já persistida em `fato_volumes_base`. Corrigido trocando as 3 por hash
determinístico de 64 bits (mesmo domínio já usado em `vehicle_key`), com o
bit de sinal mascarado pra caber sentinela negativa e manter tipo `BIGINT`
homogêneo entre as 3.

**Os valores das chaves mudaram nesta migração — de propósito, não é
regressão.** Rebuild rodado contra produção em 2026-09-09, verificado:
zero colisão nas 3 dimensões, integridade referencial completa
(`fato_volumes_base` religada contra `dim_empresa`/`dim_veiculo_atual` já
atualizadas), estabilidade confirmada com teste sintético (CNPJ novo
ordenando antes de existentes não move nenhuma chave preexistente — o
oposto do comportamento anterior). Qualquer dashboard/cache/integração
externa que tenha capturado o valor antigo de uma dessas 3 chaves precisa
saber que esse valor não é mais válido depois desta mudança — não existia
integração externa usando essas chaves até esta data, então o impacto real
foi zero, mas fica registrado pra não pegar alguém de surpresa no futuro.
