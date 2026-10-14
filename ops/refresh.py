"""Refresh public cache and generated HTML, without commit/push/agents."""
from pathlib import Path
from .github import GitHub
from .progress import build, write

def main():
    write(Path(__file__).resolve().parents[1],build(GitHub()))
    print("Public evidence refreshed. No database/model operation or push.")

if __name__=="__main__": main()
