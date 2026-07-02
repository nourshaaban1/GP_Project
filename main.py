import os
import asyncio
from computer import Computer 
from cua_agent import ComputerAgent
from cua_agent.tools.browser_tool import BrowserTool
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure OpenRouter API credentials
openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
llm_provider = os.getenv("LLM_PROVIDER", "openrouter")
base_model = os.getenv("LLM_MODEL", "z-ai/glm-5.2")  # e.g., "z-ai/glm-5.2"
llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "3000"))

# Format model string for litellm: must use "openrouter/provider/model" format
# For OpenRouter, the format is: openrouter/{model_id}
llm_model = f"openrouter/{base_model}"

# Set the API key for OpenRouter
os.environ["OPENROUTER_API_KEY"] = openrouter_api_key

# Verify the API key is set
if not openrouter_api_key:
    raise ValueError("OPENROUTER_API_KEY not found in .env file")

print(f"Configured OpenRouter:")
print(f"  Provider: {llm_provider}")
print(f"  Base Model: {base_model}")
print(f"  Formatted Model: {llm_model}")
print(f"  Temperature: {llm_temperature}")
print(f"  Max Tokens: {llm_max_tokens}")

computer = Computer(
    os_type="linux",
    provider_type="docker",
    image="trycua/cua-xfce:latest"
)

async def main():
    await computer.run()

    try:
        # Initialize ComputerAgent with OpenRouter configuration
        # The model string must be in the format: openrouter/{model_id}
        agent = ComputerAgent(
            model=llm_model,  # This tells litellm to use OpenRouter
            tools=[computer],
            temperature=llm_temperature,
            max_tokens=llm_max_tokens,
        )

        messages = [
            {
                "role": "user", 
                "content": "open firefox and download this pdf file https://ontheline.trincoll.edu/images/bookdown/sample-local-pdf.pdf then make a summarization of it and save it in a summ.txt file"
            }
        ]

        async for result in agent.run(messages):
            for item in result["output"]:
                if item["type"] == "message":
                    print(item["content"][0]["text"])
    finally:
        await computer.disconnect()

if __name__ == "__main__":
    asyncio.run(main())