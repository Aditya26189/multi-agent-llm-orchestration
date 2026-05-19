import urllib.request
import urllib.error
import json
import os
import sys

def test_gemini_api_key(api_key):
    # Using gemini-flash-latest as it's the standard fast model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    data = {
        "contents": [{
            "parts": [{"text": "Hello, this is a test. Reply with 'OK'."}]
        }]
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
    
    try:
        print(f"Testing API key (ending in ...{api_key[-4:] if len(api_key) > 4 else api_key})")
        print("Sending request to Gemini API...")
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            print("\n[SUCCESS]: API Key is valid and working!")
            
            try:
                text_response = result['candidates'][0]['content']['parts'][0]['text']
                print(f"Model response: {text_response.strip()}")
            except (KeyError, IndexError):
                print(f"Raw response: {result}")
                
            return True
            
    except urllib.error.HTTPError as e:
        print(f"\n[ERROR]: API Key test failed with HTTP {e.code}: {e.reason}")
        try:
            error_details = json.loads(e.read().decode('utf-8'))
            print(f"Error details:\n{json.dumps(error_details, indent=2)}")
            
            if e.code == 400 and "API key not valid" in str(error_details):
                print("\nThe API key provided is invalid. Please double-check it.")
            elif e.code == 403:
                print("\nPermission denied. The API key might not have access to the Gemini API, or you might be in a restricted region.")
            elif e.code == 429:
                print("\nRate limit exceeded. Your API key works, but you have made too many requests.")
                
        except Exception:
            pass
            
        return False
        
    except Exception as e:
        print(f"\n[ERROR]: An unexpected error occurred: {str(e)}")
        return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test a Gemini API key using the REST API.")
    parser.add_argument("--key", type=str, help="The API key to test. If not provided, reads GOOGLE_API_KEY from .env or environment variables.")
    args = parser.parse_args()
    
    api_key = args.key
    
    if not api_key:
        print("Looking for API key in .env file...")
        # Try to read from .env if it exists in the current directory
        try:
            with open(".env", "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GOOGLE_API_KEY=") and not line.startswith("#"):
                        api_key = "AIzaSyBgv7I6ZkvUBpGGwHqrfR01Cfvk_ZBH5BU"
                        break
        except FileNotFoundError:
            pass
            
    if not api_key:
        api_key = os.environ.get("GOOGLE_API_KEY")
        
    if not api_key:
        print("Error: No API key found.")
        print("Please provide it via --key argument, or set GOOGLE_API_KEY in your .env file or environment.")
        sys.exit(1)
        
    test_gemini_api_key(api_key)
