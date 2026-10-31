from __future__ import annotations
import os
from dataclasses import dataclass
from time import perf_counter
import httpx

class ProviderError(Exception):
    def __init__(self, message, status=502): self.status=status; super().__init__(message)

@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int

class MiniMaxProvider:
    def __init__(self):
        self.api_key=os.getenv('MINIMAX_API_KEY','').strip()
        self.url=os.getenv('MINIMAX_API_URL','https://api.minimax.cn/v1/text/chatcompletion_v2')
        self.model=os.getenv('MINIMAX_MODEL','MiniMax-M3')
    async def complete(self,messages,max_tokens=3000):
        if not self.api_key: raise ProviderError('服务尚未配置 MiniMax API Key。',503)
        started=perf_counter()
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response=await client.post(self.url,json={'model':self.model,'messages':messages,'stream':False,'max_completion_tokens':max_tokens},headers={'Authorization':f'Bearer {self.api_key}','Content-Type':'application/json'})
                response.raise_for_status(); data=response.json()
        except httpx.TimeoutException as exc: raise ProviderError('模型请求超时。',504) from exc
        except httpx.HTTPStatusError as exc: raise ProviderError('模型服务返回错误，请稍后重试。',502) from exc
        except (httpx.RequestError,ValueError) as exc: raise ProviderError('无法连接 MiniMax 或返回格式无效。') from exc
        base=data.get('base_resp') or {}
        if base.get('status_code',0)!=0: raise ProviderError('MiniMax 拒绝了本次请求。')
        choices=data.get('choices') or []; text=((choices[0].get('message') or {}).get('content') if choices else None)
        if not isinstance(text,str) or not text.strip(): raise ProviderError('模型没有返回文本回答。')
        u=data.get('usage') or {}
        return Completion(text.strip(),data.get('model') or self.model,int(u.get('prompt_tokens') or 0),int(u.get('completion_tokens') or 0),int(u.get('total_tokens') or 0),round((perf_counter()-started)*1000))

@dataclass
class OrchestrationResult:
    answer: str
    model: str
    plan: str
    stages: list[str]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int

async def run_orchestration(prompt):
    provider=MiniMaxProvider(); stages=[]; p=c=t=l=0; nl=chr(10)
    def add(x):
        nonlocal p,c,t,l
        p+=x.prompt_tokens; c+=x.completion_tokens; t+=x.total_tokens; l+=x.latency_ms
    plan=await provider.complete([{'role':'system','content':'你是任务规划器。只输出简洁执行计划，不要回答原问题。'},{'role':'user','content':'用户问题：'+nl+prompt+nl+nl+'请给出最多 5 步的执行计划。'}],800); add(plan); stages.append('规划')
    draft=await provider.complete([{'role':'system','content':'你是执行器。根据用户问题和计划完成任务。'},{'role':'user','content':'用户问题：'+nl+prompt+nl+nl+'执行计划：'+nl+plan.text+nl+nl+'请输出结构化草稿。'}],5000); add(draft); stages.append('执行')
    review=await provider.complete([{'role':'system','content':'你是结果复查器。直接输出修订后的最终答案。'},{'role':'user','content':'用户问题：'+nl+prompt+nl+nl+'草稿：'+nl+draft.text+nl+nl+'请检查遗漏和编造后输出最终答案。'}],5000); add(review); stages.append('复查')
    return OrchestrationResult(review.text,review.model,plan.text,stages,p,c,t,l)
