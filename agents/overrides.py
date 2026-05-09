import logging

async def apply_approved_prompt_rewrites(db_session):
    """
    Fetch approved prompt rewrites from the database and override the module-level constants.
    This enables the self-improving loop without restarting the container.
    """
    from sqlalchemy import text
    try:
        result = await db_session.execute(text("SELECT agent_id, proposed_prompt FROM prompt_rewrites WHERE status = 'approved'"))
        rows = result.mappings().all()
        
        for row in rows:
            agent_id = row["agent_id"]
            prompt = row["proposed_prompt"]
            
            if agent_id == "decomposition":
                import agents.decomposition
                agents.decomposition.DECOMP_PROMPT = prompt
            elif agent_id == "retrieval":
                # Note: Retrieval has 2 prompts, but we override the first one by default if not specified.
                import agents.retrieval
                agents.retrieval.RETRIEVAL_PROMPT_HOP1 = prompt
            elif agent_id == "critique":
                import agents.critique
                agents.critique.CRITIQUE_PROMPT = prompt
            elif agent_id == "synthesis":
                import agents.synthesis
                agents.synthesis.SYNTHESIS_PROMPT = prompt
            elif agent_id == "orchestrator":
                import agents.orchestrator
                agents.orchestrator.ORCHESTRATOR_SYSTEM = prompt
                
        if rows:
            logging.info(f"Applied {len(rows)} approved prompt rewrites.")
            
    except Exception as e:
        logging.error(f"Failed to apply prompt rewrites: {e}")
