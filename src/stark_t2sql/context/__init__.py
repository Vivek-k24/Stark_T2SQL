"""Source-only FR-3 physical and semantic context compilers.

NFR-6 normally reserves the context builder to the human author. The current
Prompt 3 instruction expressly permits a Codex draft; it does not authorize
runtime, database, model, parser, or evaluation invocation. Context filtering
minimizes disclosure; PostgreSQL grants/RLS and the validator enforce access.
Prompt 4 owns prompt assembly and the single answer() pipeline.
"""
