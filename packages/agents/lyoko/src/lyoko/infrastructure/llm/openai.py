"""OpenAI / LangChain LLM infrastructure adapter for LYOKO."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.infrastructure.observability.langfuse import get_langfuse_callback_handler

logger = logging.getLogger("lyoko.infrastructure.llm.openai")

DIAGNOSTIC_SYSTEM_PROMPT = """You are LYOKO (Live Yaml Optimization & K8s Orchestration), the autonomous remediation agent.
Analyze pod failure events, diagnose root causes (e.g., OOMKilled, CrashLoopBackOff), and provide precise recommendations."""


class OpenAILLMAdapter(LLMClientInterface):
    """LLM adapter implementing LLMClientInterface backed by ChatOpenAI and LangChain."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ) -> None:
        self.model_name = model_name
        self.temperature = temperature
        self._api_key = api_key
        self._client: ChatOpenAI | None = None

    @property
    def client(self) -> ChatOpenAI:
        if self._client is None:
            api_key = self._api_key or "sk-dummy"
            self._client = ChatOpenAI(
                model=self.model_name,
                temperature=self.temperature,
                api_key=api_key,
            )
        return self._client

    async def chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
        tools: list[Any] | None = None,
    ) -> str:
        """Process conversational prompt with optional system prompt, tools, and Langfuse tracing."""
        cb = get_langfuse_callback_handler()
        config: dict[str, Any] = {}
        if cb:
            config["callbacks"] = [cb]

        if tools:
            try:
                agent = create_react_agent(
                    model=self.client,
                    tools=tools,
                    prompt=system_prompt,
                )
                messages = [HumanMessage(content=prompt)]
                result = await agent.ainvoke(
                    {"messages": messages},
                    config=config if config else None,
                )
                last_message = result["messages"][-1]
                return str(last_message.content)
            except Exception as e:
                logger.error("Error executing ReAct agent with tools: %s", e)
                # Fallback to standard chat without tools
                pass

        messages: list[Any] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        response = await self.client.ainvoke(messages, config=config if config else None)
        return str(response.content)

    async def analyze_incident(
        self,
        alert_name: str,
        pod_name: str,
        namespace: str,
        diagnostics: Any,
    ) -> str:
        """Analyze pod failure diagnostics and determine root cause."""
        prompt = f"""
        Alert: {alert_name}
        Target Pod: {pod_name} (Namespace: {namespace})
        Diagnostics: {diagnostics}

        Identify the root cause in 1-2 sentences. Is it OOMKilled, Misconfiguration, CrashLoop, or Unknown?
        """
        return await self.chat(prompt=prompt, system_prompt=DIAGNOSTIC_SYSTEM_PROMPT)

    async def generate_remediation_plan(self, context: dict[str, Any]) -> str:
        """Generate automated remediation steps from diagnostic incident context."""
        prompt = f"Generate remediation plan for incident context: {context}"
        return await self.chat(prompt=prompt, system_prompt=DIAGNOSTIC_SYSTEM_PROMPT)
