import os
import sys

# Add current directory to path so we can import from agents
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.base import BaseAgent

class DummyAgent(BaseAgent):
    def __init__(self, agent_id: str):
        super().__init__(agent_id=agent_id)
        
    async def run(self, context, budget_mgr, redis_pub=None):
        pass

def test_keys():
    agent_ids = [
        "orchestrator", 
        "retrieval", 
        "synthesis", 
        "critique", 
        "decomposition", 
        "compression", 
        "meta"
    ]
    
    print(f"{'AGENT ID':<15} | {'API KEY (LAST 5)':<15}")
    print("-" * 35)
    
    for agent_id in agent_ids:
        # Create an agent instance
        agent = DummyAgent(agent_id=agent_id)
        
        # Access the private client's api key to verify
        api_key = agent._client.api_key
        
        # Mask the key for security, showing only the last 5 characters
        masked_key = f"...{api_key[-5:]}" if api_key and len(api_key) > 5 else str(api_key)
        
        print(f"{agent_id:<15} | {masked_key:<15}")

if __name__ == "__main__":
    test_keys()
