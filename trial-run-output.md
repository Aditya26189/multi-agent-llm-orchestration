Content-Type: application/json"   -d '{"query": "What is Python and who created it?"}'
id: 0
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "orchestrator", "used_tokens": 473, "max_tokens": 8192, "remaining_tokens": 7719, "pct_used": 5.8, "id": 0}

id: 0
event: HANDOFF
data: {"event_type": "HANDOFF", "next_agent": "decomposition", "reasoning": "The current turn is 0, and no agents have been invoked yet. According to the routing logic, when turn=0, the 'decomposition' agent should be invoked first to break down the query into sub-tasks. There are no budget warnings that would necessitate routing to 'compression'.", "confidence": 1.0, "turn": 0, "id": 0}

id: 1
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "decomposition", "used_tokens": 249, "max_tokens": 8192, "remaining_tokens": 7943, "pct_used": 3.0, "id": 1}

id: 2
event: AGENT_START
data: {"event_type": "AGENT_START", "agent_id": "decomposition", "id": 2}

id: 3
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "decomposition", "used_tokens": 362, "max_tokens": 8192, "remaining_tokens": 7830, "pct_used": 4.4, "id": 3}

id: 4
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "orchestrator", "used_tokens": 969, "max_tokens": 8192, "remaining_tokens": 7223, "pct_used": 11.8, "id": 4}

id: 1
event: HANDOFF
data: {"event_type": "HANDOFF", "next_agent": "retrieval", "reasoning": "The 'decomposition' agent has already been invoked (as indicated by 'agents_routed_to' and the presence of 'sub_tasks_pending'). According to the routing logic, after 'decomposition' is done and 'retrieval' is NOT done (which it isn't, as 'chunks_retrieved' is 0), the next agent to invoke is 'retrieval'. The query is factual and requires information lookup, making retrieval a necessary step.", "confidence": 1.0, "turn": 1, "id": 1}

id: 5
event: AGENT_START
data: {"event_type": "AGENT_START", "agent_id": "retrieval", "id": 5}

id: 6
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "retrieval", "used_tokens": 516, "max_tokens": 8192, "remaining_tokens": 7676, "pct_used": 6.3, "id": 6}

id: 7
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "retrieval", "used_tokens": 1151, "max_tokens": 8192, "remaining_tokens": 7041, "pct_used": 14.1, "id": 7}

id: 8
event: TOKEN
data: {"event_type": "TOKEN", "agent_id": "retrieval", "token": "Python is a high-level, interpreted, general-purpose programming language. [CHUNK:ee2f6813-47d5-4b51-b946-52cd65c101c5] It was created by Guido van Rossum and was first released in 1991. [CHUNK:ee2f6813-47d5-4b51-b946-52cd65c101c5] As for its features and applications, its nature as a high-level, interpreted, general-purpose language defines some of its key characteristics. [CHUNK:ee2f6813-47d5-4b51-b946-52cd65c101c5] A common application for Python is building APIs, exemplified by frameworks like FastAPI. [CHUNK:86eb5d10-842b-4d84-9c8c-04ae9b2fbdb5] FastAPI is a modern, fast web framework that utilizes Python 3.7+ for this purpose. [CHUNK:86eb5d10-842b-4d84-9c8c-04ae9b2fbdb5]", "id": 8}

id: 9
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "orchestrator", "used_tokens": 1475, "max_tokens": 8192, "remaining_tokens": 6717, "pct_used": 18.0, "id": 9}

id: 10
event: AGENT_START
data: {"event_type": "AGENT_START", "agent_id": "critique", "id": 10}

id: 11
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "critique", "used_tokens": 1680, "max_tokens": 8192, "remaining_tokens": 6512, "pct_used": 20.5, "id": 11}

id: 12
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "critique", "used_tokens": 1691, "max_tokens": 8192, "remaining_tokens": 6501, "pct_used": 20.6, "id": 12}

id: 13
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "orchestrator", "used_tokens": 1987, "max_tokens": 8192, "remaining_tokens": 6205, "pct_used": 24.3, "id": 13}

id: 14
event: AGENT_START
data: {"event_type": "AGENT_START", "agent_id": "synthesis", "id": 14}

id: 15
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "synthesis", "used_tokens": 1031, "max_tokens": 8192, "remaining_tokens": 7161, "pct_used": 12.6, "id": 15}

id: 16
event: TOKEN
data: {"event_type": "TOKEN", "agent_id": "synthesis", "token": "Python is a high-level, interpreted, general-purpose programming language [CHUNK:ee2f6813-47d5-4b51-b9", "id": 16}

id: 17
event: TOKEN
data: {"event_type": "TOKEN", "agent_id": "synthesis", "token": "46-52cd65c101c5]. It was created by Guido van Rossum and was first released in 1991 [CHUNK:ee2f6813-47d5", "id": 17}

id: 18
event: TOKEN
data: {"event_type": "TOKEN", "agent_id": "synthesis", "token": "-4b51-b946-52cd65c101c5]. As for its features and applications, its nature as a high-level, interpreted, general-purpose language defines some of its", "id": 18}    

id: 19
event: TOKEN
data: {"event_type": "TOKEN", "agent_id": "synthesis", "token": " key characteristics [REASONING]. A common application for Python is building APIs, exemplified by frameworks like FastAPI [CHUNK:86eb5d10-842b-4d84-9c8c-0", "id": 19}

id: 20
event: TOKEN
data: {"event_type": "TOKEN", "agent_id": "synthesis", "token": "4ae9b2fbdb5]. FastAPI is a modern, fast web framework that utilizes Python 3.7+ for this purpose [CHUNK:86eb5d10-842b-4d84", "id": 20}

id: 21
event: TOKEN
data: {"event_type": "TOKEN", "agent_id": "synthesis", "token": "-9c8c-04ae9b2fbdb5].\n\nResolution Log (JSON):\n{\"resolutions\": []}", "id": 21}

id: 22
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "synthesis", "used_tokens": 1289, "max_tokens": 8192, "remaining_tokens": 6903, "pct_used": 15.7, "id": 22}

id: 23
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "orchestrator", "used_tokens": 2505, "max_tokens": 8192, "remaining_tokens": 5687, "pct_used": 30.6, "id": 23}

id: 24
event: done
data: {"event_type": "done", "job_id": "e08df389-9e8b-4a87-8445-7c8dfd885441", "final_answer": "Python is a high-level, interpreted, general-purpose programming language . It was created by Guido van Rossum and was first released in 1991 . As for its features and applications, its nature as a high-level, interpreted, general-purpose language defines some of its key characteristics . A common application for Python is building APIs, exemplified by frameworks like FastAPI . FastAPI is a modern, fast web framework that utilizes Python 3.7+ for this purpose .", "provenance": [{"sentence": "Python is a high-level, interpreted, general-purpose programming language [CHUNK:ee2f6813-47d5-4b51-b946-52cd65c101c5]. It was created by Guido van Rossum and was first released in 1991 [CHUNK:ee2f6813-47d5-4b51-b946-52cd65c101c5]. As for its features and applications, its nature as a high-level, interpreted, general-purpose language defines some of its key characteristics [REASONING]. A common application for Python is building APIs, exemplified by frameworks like FastAPI [CHUNK:86eb5d10-842b-4d84-9c8c-04ae9b2fbdb5]. FastAPI is a modern, fast web framework that utilizes Python 3.7+ for this purpose [CHUNK:86eb5d10-842b-4d84-9c8c-04ae9b2fbdb5].", "source_agent": "synthesis", "source_chunk_id": null}], "id": 24}
