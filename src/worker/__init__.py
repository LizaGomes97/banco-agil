"""Worker de curadoria (ADR-023).

Módulo independente que consome `memory_staging` e gera candidatos de
padrões aprendidos (routing, templates, lições). Roda em processo
separado para NÃO competir com o hot path do chat.
"""
