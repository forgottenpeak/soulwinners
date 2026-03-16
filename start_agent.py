import asyncio
from bot.agent.autonomous_engine import agent

if __name__ == "__main__":
    asyncio.run(agent.autonomous_loop())
