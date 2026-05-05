"""Autenticacao multi-tenant do SDK de analytics.

Fase 1 do plano-garantias-sdk-backend.md: emissao de sdk_jwt RS256 com TTL
curto a partir de publishable_key, validacao de Origin contra allowlist,
middleware de scope/audience, guard de Socket.IO.
"""
