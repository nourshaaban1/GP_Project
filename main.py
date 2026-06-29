
import os
import asyncio
from computer import Computer 
from agent import ComputerAgent
from agent.tools.browser_tool import BrowserTool
from dotenv import load_dotenv
load_dotenv()
   

os.environ["CUA_API_KEY"] = os.getenv("CUA_API_KEY")

computer =  Computer(
            os_type="linux",
            provider_type="docker",
            image="trycua/cua-xfce:latest"
            )

async def main():
    await computer.run()  

    try:
        agent = ComputerAgent(
            model="cua/anthropic/claude-3-5-sonnet-20241022",
            tools=[computer],
            temperature=0.7,
        )

        messages = [{"role": "user", "content":"open firefox and download this pdf file https://ontheline.trincoll.edu/images/bookdown/sample-local-pdf.pdf then make a summarization of it and save it in a summ.txt file"}]

        async for result in agent.run(messages):
            for item in result["output"]:
                if item["type"] == "message":
                    print(item["content"][0]["text"])
    finally:
        await computer.disconnect()

asyncio.run(main())