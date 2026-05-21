"""Entry point for the email polling loop. Run from project root: python run_handler.py"""
from agent.email_handler import run_loop

if __name__ == "__main__":
    run_loop(interval_seconds=60)
