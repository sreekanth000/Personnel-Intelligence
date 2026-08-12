import logging
from app.connectors.gmail_auth import GmailAuthService

logging.basicConfig(level=logging.INFO)

def main():
    auth = GmailAuthService()
    print("Starting interactive auth flow...")
    print("This will open a browser window for you to log in.")
    
    # We remove the expired token if it exists so it doesn't try to use it
    if auth.token_path.exists():
        print(f"Removing old token at {auth.token_path}")
        auth.token_path.unlink()
        
    auth.authenticate_interactive(port=8080)
    print(f"Auth successful! Token saved to {auth.token_path}")

if __name__ == "__main__":
    main()
