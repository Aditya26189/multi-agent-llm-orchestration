import os

def check_keys():
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
        # This is exactly how BaseAgent resolves the key
        key_env = f"GOOGLE_API_KEY_{agent_id.upper()}"
        api_key = os.environ.get(key_env) or os.environ.get("GOOGLE_API_KEY", "NOT FOUND")
        
        # Mask the key for security, showing only the last 5 characters
        masked_key = f"...{api_key[-5:]}" if len(api_key) > 5 else str(api_key)
        
        print(f"{agent_id:<15} | {masked_key:<15}")

if __name__ == "__main__":
    check_keys()
