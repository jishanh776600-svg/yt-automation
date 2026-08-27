"""
Helper script to display your exact secrets for GitHub Repository setup.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

token_file = PROJECT_ROOT / "token.json"
client_file = PROJECT_ROOT / "client_secret.json"
env_file = PROJECT_ROOT / ".env"

print("=" * 60)
print("GITHUB REPOSITORY SECRETS GUIDE")
print("=" * 60)
print("\nIn your GitHub Repo: Go to Settings -> Secrets and variables -> Actions -> New repository secret\n")

if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "PEXELS_API_KEY=" in line:
            print("1. Secret Name: PEXELS_API_KEY")
            print("   Value:")
            print(line.split("=", 1)[1].strip())
            print("-" * 50)
        elif "GEMINI_API_KEY=" in line:
            print("2. Secret Name: GEMINI_API_KEY")
            print("   Value:")
            print(line.split("=", 1)[1].strip())
            print("-" * 50)

if token_file.exists():
    print("3. Secret Name: TOKEN_JSON")
    print("   Value:")
    print(token_file.read_text(encoding="utf-8").strip())
    print("-" * 50)

if client_file.exists():
    print("4. Secret Name: CLIENT_SECRET_JSON")
    print("   Value:")
    print(client_file.read_text(encoding="utf-8").strip())
    print("=" * 60)
