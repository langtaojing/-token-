from __future__ import annotations
import os
import base64
from dataclasses import dataclass
from time import perf_counter
import httpx

class ProviderError(Exception):
    def __init__(self, message, status=502, kind="provider", usage=None):
        self.status=status
        self.kind=kind
        self.usage=usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        super().__init__(message)

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
    async def complete(self,messages,max_tokens=3000,model=None,effort=None):
        try:
            return await self._complete_once(messages,max_tokens,model,effort)
        except ProviderError as exc:
            if exc.kind != "empty_content":
                raise
            try:
                result = await self._complete_once(messages,min(max_tokens*2,12000),model,effort)
            except ProviderError as retry_error:
                retry_error.usage = {
                    key: retry_error.usage[key]+exc.usage[key]
                    for key in ("prompt_tokens","completion_tokens","total_tokens")
                }
                raise
            result.prompt_tokens += exc.usage["prompt_tokens"]
            result.completion_tokens += exc.usage["completion_tokens"]
            result.total_tokens += exc.usage["total_tokens"]
            return result

    async def _complete_once(self,messages,max_tokens,model=None,effort=None):
        if not self.api_key: raise ProviderError('服务尚未配置 MiniMax API Key。',503)
        started=perf_counter()
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                payload={'model':model or self.model,'messages':messages,'stream':False,'max_completion_tokens':max_tokens}
                if effort: payload['reasoning_effort']=effort
                response=await client.post(self.url,json=payload,headers={'Authorization':f'Bearer {self.api_key}','Content-Type':'application/json'})
                response.raise_for_status(); data=response.json()
        except httpx.TimeoutException as exc: raise ProviderError('模型请求超时。',504) from exc
        except httpx.HTTPStatusError as exc: raise ProviderError('模型服务返回错误，请稍后重试。',502) from exc
        except (httpx.RequestError,ValueError) as exc: raise ProviderError('无法连接 MiniMax 或返回格式无效。') from exc
        base=data.get('base_resp') or {}
        if base.get('status_code',0)!=0: raise ProviderError('MiniMax 拒绝了本次请求。')
        u=data.get('usage') or {}
        counts={key:int(u.get(key) or 0) for key in ('prompt_tokens','completion_tokens','total_tokens')}
        choices=data.get('choices') or []; text=((choices[0].get('message') or {}).get('content') if choices else None)
        if not isinstance(text,str) or not text.strip():
            raise ProviderError('模型没有返回文本回答。',kind='empty_content',usage=counts)
        return Completion(text.strip(),data.get('model') or self.model,int(u.get('prompt_tokens') or 0),int(u.get('completion_tokens') or 0),int(u.get('total_tokens') or 0),round((perf_counter()-started)*1000))

    async def analyze_image(self, image_bytes, mime_type, prompt, max_tokens=4000):
        encoded=base64.b64encode(image_bytes).decode('ascii')
        messages=[{'role':'user','content':[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':f'data:{mime_type};base64,{encoded}'}}]}]
        return await self.complete(messages,max_tokens,model='MiniMax-M3.1-Flash',effort='low')

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

async def run_orchestration(prompt, mode="fast"):
    provider=MiniMaxProvider(); stages=[]; p=c=t=0; nl=chr(10); started=perf_counter()
    def total_latency(): return round((perf_counter()-started)*1000)
    def add(x):
        nonlocal p,c,t
        p+=x.prompt_tokens; c+=x.completion_tokens; t+=x.total_tokens
    if mode == "fast":
        answer = await provider.complete([
            {'role':'system','content':'请直接回答用户问题，给出具体、有用的内容。信息不足时说明假设，不要只给简短一句话。'},
            {'role':'user','content':prompt},
        ], 4000, model='MiniMax-M3.1-Flash', effort='low')
        add(answer)
        return OrchestrationResult(answer.text,answer.model,'', ['快速回答'],p,c,t,total_latency())
    try:
        plan=await provider.complete([{'role':'system','content':'你是任务规划器。只输出简洁执行计划，不要回答原问题。'},{'role':'user','content':'用户问题：'+nl+prompt+nl+nl+'请给出最多 5 步的执行计划。'}],1500)
        add(plan)
        plan_text=plan.text
        stages.append('规划')
    except ProviderError as exc:
        if exc.kind != 'empty_content': raise
        p+=exc.usage['prompt_tokens']; c+=exc.usage['completion_tokens']; t+=exc.usage['total_tokens']
        plan_text='1. 理解需求和约束；2. 给出具体方案；3. 检查遗漏并明确不确定处。'
        stages.append('规划（兜底）')
    try:
        draft=await provider.complete([{'role':'system','content':'你是执行器。根据用户问题和计划完成任务。'},{'role':'user','content':'用户问题：'+nl+prompt+nl+nl+'执行计划：'+nl+plan_text+nl+nl+'请输出结构化草稿。'}],8000)
    except ProviderError as exc:
        if exc.kind != 'empty_content': raise
        p+=exc.usage['prompt_tokens']; c+=exc.usage['completion_tokens']; t+=exc.usage['total_tokens']
        stages.append('执行（备用请求）')
        draft=await provider.complete([{'role':'user','content':'请直接回答下面的问题，给出具体可执行的内容：'+nl+prompt}],12000)
    add(draft); stages.append('执行')
    try:
        review=await provider.complete([{'role':'system','content':'你是结果复查器。直接输出修订后的最终答案。'},{'role':'user','content':'用户问题：'+nl+prompt+nl+nl+'草稿：'+nl+draft.text+nl+nl+'请检查遗漏和编造后输出最终答案。'}],8000)
        add(review)
        stages.append('复查')
        return OrchestrationResult(review.text,review.model,plan_text,stages,p,c,t,total_latency())
    except ProviderError as exc:
        if exc.kind != 'empty_content': raise
        p+=exc.usage['prompt_tokens']; c+=exc.usage['completion_tokens']; t+=exc.usage['total_tokens']
        stages.append('复查（返回草稿）')
        return OrchestrationResult(draft.text,draft.model,plan_text,stages,p,c,t,total_latency())
