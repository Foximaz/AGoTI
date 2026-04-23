import asyncio
from typing import List, Dict, Optional
from abc import ABC, abstractmethod
import logging
import json
import re
from logging.handlers import RotatingFileHandler
from openai import AsyncOpenAI
from .utils import Message

logger = logging.getLogger(__name__)

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
            api_key: str,
            base_url: str,
            model_name: str,
            cut_reasoning: bool=True,
            generation_config: Dict=DEFAULT_GENERATION_CONFIG,
            max_concurrent_requests: int=10,
            log_to_file: bool=False,
            log_file_path: str=None
            ):
        self.async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name
        self.cut_reasoning = cut_reasoning
        self.generation_config = generation_config
        self.log_to_file = log_to_file
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        
        if self.log_to_file:
            if log_file_path is None:
                log_file_path = f"{self.model_name.replace("/", "_")}.log"
            self._setup_file_logger(log_file_path)
    
    def _setup_file_logger(self, log_file_path: str):
        self.file_logger = logging.getLogger(f"llm_file_logger_{self.model_name}")
        self.file_logger.setLevel(logging.INFO)
        
        file_handler = RotatingFileHandler(
            log_file_path, 
            maxBytes=10*1024*1024, # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        self.file_logger.addHandler(file_handler)
        self.file_logger.propagate = False
    
    async def generate(
            self,
            messages,
            generation_config=None
            ):
        if generation_config is None:
            generation_config = self.generation_config
        
        async with self.semaphore:
            response = await self.async_client.chat.completions.create(
                messages=messages, model=self.model_name, **generation_config)
            
            if response.choices is None:
                result = None
                logger.error(
                    f"Model ({self.model_name}) failed to generate completion - no choices in response. Messages:\n"
                    f"{json.dumps(messages, indent=4, ensure_ascii=False)}"
                )
                return None
            
            message = response.choices[0].message
            result = message.content

            if result is None:
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    error_message = f"Tool calls received: {message.tool_calls}"
                elif hasattr(message, 'refusal') and message.refusal:
                    error_message = f"Model refused: {message.refusal}"
                elif hasattr(message, 'reasoning_content'):
                    error_message = "Got reasoning content instead of text"
                else:
                    error_message = "No content and no tool calls in response"
                logger.error(
                    f"Model ({self.model_name}) failed to generate completion. {error_message}. Finish reason: {response.choices[0].finish_reason}. Messages:\n"
                    f"{json.dumps(messages, indent=4, ensure_ascii=False)}"
                )
                return None
            
            if self.cut_reasoning:
                result = re.sub(r"(.*<\/think>\s*)", "", result, re.DOTALL)
            
            if self.log_to_file:
                self.file_logger.info(
                    f"Messages: {json.dumps(messages, indent=2, ensure_ascii=False)}\n"
                    f"{result if result else 'None'}"
                )
            return result
