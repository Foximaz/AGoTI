from typing import List, Dict, Optional
from abc import ABC, abstractmethod
from openai import AsyncOpenAI
from .utils import Message

DEFAULT_GENERATION_CONFIG = {
    "temperature": 0.01,
    "top_p": 0.9,
    "max_tokens": 1000,
    "extra_body": {
        "repetition_penalty": 1.0,
        "guided_choice": None,
        "add_generation_prompt": True,
        "guided_regex": None
        }
}

class LLM(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: List[Message],
        generation_config: Optional[Dict]=None
        ) -> str|None:
        pass

class ApiVLLMModel(LLM):
    def __init__(
            self,
            api_key,
            base_url,
            model_name,
            generation_config=DEFAULT_GENERATION_CONFIG
            ):
        self.async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        self.model_name = model_name
        self.generation_config = generation_config
    
    async def generate(
            self,
            messages,
            generation_config=None
            ):
        if generation_config is None:
            generation_config = self.generation_config
        
        response = await self.async_client.chat.completions.create(
            messages=messages, model=self.model_name, **generation_config)
        if response.choices is None:
            #TODO: process error
            return None
        return response.choices[0].message.content
        