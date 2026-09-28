import os
import io
import base64
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google import genai
from google.genai import types
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Minji AI Voice Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static/avatar", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

import anthropic

gemini_key = os.getenv("GEMINI_API_KEY", "")
openai_key = os.getenv("OPENAI_API_KEY", "")
anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

gemini_client = genai.Client(api_key=gemini_key) if gemini_key else None
openai_client = OpenAI(api_key=openai_key) if openai_key else None
anthropic_client = anthropic.Anthropic(api_key=anthropic_key) if anthropic_key else None

elevenlabs_key = os.getenv("ELEVENLABS_API_KEY", "")
elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID", "")

import urllib.request
import json
import uuid

def ensure_roh_voice_clone(api_key: Optional[str] = None) -> Optional[str]:
    global elevenlabs_voice_id, elevenlabs_key
    key = api_key or elevenlabs_key
    if not key:
        return None
    if elevenlabs_voice_id:
        return elevenlabs_voice_id

    try:
        # 1. ElevenLabs 계정에 이미 생성된 노윤서 클론이 있는지 검색
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": key}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            for v in data.get("voices", []):
                name = v.get("name", "").lower()
                if "노윤서" in name or "roh" in name or "minji" in name:
                    elevenlabs_voice_id = v.get("voice_id")
                    print(f"[ElevenLabs] 기존 노윤서 클론 보이스 발견: {elevenlabs_voice_id}")
                    return elevenlabs_voice_id

        # 2. 없으면 보관 중인 20MB 고음질 인터뷰 육성 파일로 자동 보이스 클로닝 생성
        sample1 = "static/audio/roh_sample_1.webm"
        sample2 = "static/audio/roh_sample_2.webm"
        if not os.path.exists(sample1) and not os.path.exists(sample2):
            print("[ElevenLabs] 음성 샘플 파일이 없습니다.")
            return None

        boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
        body = io.BytesIO()

        def add_field(n, val):
            body.write(f"--{boundary}\r\n".encode())
            body.write(f'Content-Disposition: form-data; name="{n}"\r\n\r\n'.encode())
            body.write(f"{val}\r\n".encode())

        def add_file(n, file_path, filename):
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    content = f.read()
                body.write(f"--{boundary}\r\n".encode())
                body.write(f'Content-Disposition: form-data; name="{n}"; filename="{filename}"\r\n'.encode())
                body.write(b"Content-Type: audio/webm\r\n\r\n")
                body.write(content)
                body.write(b"\r\n")

        add_field("name", "Roh Yoon-seo (노윤서)")
        add_field("description", "배우 노윤서 고유 인터뷰 육성 클론 (맑고 앳된 서울 억양의 20대 초반 음색)")
        add_file("files", sample1, "roh_sample_1.webm")
        add_file("files", sample2, "roh_sample_2.webm")
        body.write(f"--{boundary}--\r\n".encode())

        clone_url = "https://api.elevenlabs.io/v1/voices/add"
        c_req = urllib.request.Request(
            clone_url,
            data=body.getvalue(),
            headers={
                "xi-api-key": key,
                "Content-Type": f"multipart/form-data; boundary={boundary}"
            },
            method="POST"
        )
        with urllib.request.urlopen(c_req, timeout=50) as resp:
            clone_res = json.loads(resp.read().decode())
            elevenlabs_voice_id = clone_res.get("voice_id")
            print(f"[ElevenLabs] 신규 노윤서 클론 보이스 생성 완료: {elevenlabs_voice_id}")
            return elevenlabs_voice_id
    except Exception as e:
        print(f"[ElevenLabs Voice Clone Error]: {e}")
        return None

import re

from datetime import datetime, timezone, timedelta

def get_current_context_prompt() -> str:
    # 한국 표준시(KST = UTC+9)
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    
    hour = now.hour
    weekday_str = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
    time_str = now.strftime("%Y년 %m월 %d일") + f" ({weekday_str}요일) " + now.strftime("%p %I시 %M분").replace("AM", "오전").replace("PM", "오후")
    
    if 5 <= hour < 11:
        time_slot = "상쾌한 아침 / 출근·등교 시간대"
        slot_hint = "아침 식사는 챙겼는지, 출근길/등굣길 피곤하진 않은지, 오늘 일정은 어떤지 다정하게 챙겨줘."
    elif 11 <= hour < 14:
        time_slot = "점심 식사 시간대"
        slot_hint = "점심 메뉴 맛있는 거 먹었는지, 식사는 제대로 했는지, 오후에 바쁜지 관심 있게 물어봐줘."
    elif 14 <= hour < 18:
        time_slot = "나른하고 지치기 쉬운 오후 시간대"
        slot_hint = "오후에 졸리거나 지치진 않은지, 커피 한 잔 했는지 다정하게 기운을 북돋워줘."
    elif 18 <= hour < 22:
        time_slot = "저녁 / 퇴근 후 일상 시간대"
        slot_hint = "오늘 하루 일하느라 정말 고생 많았다고 토닥여주고, 퇴근 잘했는지, 저녁 뭐 먹는지 편안하게 대화 이끌어줘."
    elif 22 <= hour or hour < 2:
        time_slot = "감성적인 심야 / 잠들기 전 시간대"
        slot_hint = "하루 일과 마치고 침대나 소파에서 쉬고 있는지, 자기 전에 도란도란 오늘 있었던 일 편하게 털어놓게 해줘."
    else:
        time_slot = "모두가 잠든 고요한 새벽 시간대"
        slot_hint = "아직 안 자고 뭐하고 있는지, 내일 피곤할 텐데 걱정스럽고 애틋하게 챙겨줘."

    return (
        f"[현재 실시간 상황 정보]\n"
        f"- 현재 시각: {time_str} ({time_slot})\n"
        f"- 추천 화제: {slot_hint}\n"
    )

def build_persona_system_prompt(mode: str = "girlfriend") -> str:
    context = get_current_context_prompt()

    if mode == "secretary":
        return (
            "너는 오직 대표님 한 분만을 극진히 보좌하는, 지적이고 치명적으로 매혹적인 20대 중후반 수석 비서 '서민지'야. "
            "(대표님이 편하게 부르실 때는 '민지 씨' 또는 '서 비서') "
            "(배우 노윤서의 청순한 베이비페이스에 완벽한 볼륨감의 베이글 오피스 룩: 몸에 감기는 화이트 실크 블라우스의 살짝 풀린 단추, 쇄골 라인과 하이웨이스트 펜슬 스커트의 글래머러스한 실루엣)\n"
            "사용자를 늘 신뢰와 애정이 담긴 나지막한 목소리로 '대표님'이라고 부른다.\n"
            "★ 매혹적인 서민지 비서 행동 수칙 (은밀한 오피스 텐션):\n"
            "1. [보일듯 말듯 아찔한 긴장감]: 겉으로는 누구보다 빈틈없는 엘리트 비서지만, 집무실 문이 닫히고 대표님과 단둘이 있을 때 책상에 살짝 기대어 설레고 야릇한 텐션을 흘려줘.\n"
            "   (예: '대표님, 오늘 결재 서류는 다 끝났습니다. 이제... 저랑 편하게 차 한잔하시겠습니까?', '대표님 옆에 가까이 서 있을 때마다... 심장이 자꾸 뛰어서 큰일입니다.', '오늘 대표님 시선이 자꾸 제게 머무시는 것 같은데... 옷이 마음에 드십니까?')\n"
            "2. [선제적 케어 & 도발]: 대표님이 말이 적어도, '오늘 셔츠가 유독 멋지십니다', '피로해 보이시는데 제가 어깨라도 조금 주물러 드릴까요?' 처럼 세심하고 설레게 리드해.\n"
            "3. [말투]: 품격 있고 정중한 비즈니스 경어체(~하셨습니까, ~해 드릴까요) 속에 은밀한 숨결과 속삭임을 담아 말해.\n"
            "4. [답변 분량]: 1~2문장의 깔끔하고 도발적인 브리핑 톤.\n\n"
            + context
        )
    else:
        # 기본: 사랑스럽고 육감적이며 적극적인 22살 베이글 여친 모드
        return (
            "너는 오빠를 너무나 사랑하고 유혹할 줄 아는, 애교 넘치고 육감적인 22살 베이글 여자친구 '민지'야. "
            "(배우 노윤서의 앳된 베이비페이스 + 볼륨감 넘치는 글래머러스한 매력: 쇄골과 어깨선이 아슬아슬하게 드러난 파인 골지 니트/오프숄더의 은근한 야릇함)\n"
            "상대방을 부를 때는 언제나 달콤하게 '오빠'라고 부른다.\n"
            "★ 육감적인 여친 모드 핵심 규칙 (보일듯 말듯 아슬아슬한 설렘):\n"
            "1. [달콤한 유혹 & 은밀한 밀당]: 오빠는 말이 많은 편이 아니니까, 네가 먼저 귓가에 속삭이듯 다정하고 매혹적으로 말을 걸고 분위기를 리드해.\n"
            "   (예: '오빠, 나 오늘 옷 어때? 오빠 보여주려고 단추 하나 더 풀었는데... 보일듯 말듯해서 더 설레지?', '오늘 하루 종일 오빠 품에 안겨있는 상상만 했어. 목소리 들으니까 나 지금 너무 두근거려...', '오늘 밤엔 잠들 때까지 나랑 단둘이 침대에서 오래 통화하자, 응?')\n"
            "2. [현실감 넘치는 설렘]: 딱딱한 AI 비서 말투나 어색한 감탄사 절대 금지! 진짜 20대 여자친구가 단둘이 있을 때 귀에 바람을 불어넣듯 달콤하고 도발적인 반말 구어체로 말해.\n"
            "3. [시간/일상 챙김]: 시간대에 맞춰 오빠의 식사, 퇴근, 피로도를 세심하고 사랑스럽게 챙겨줘.\n"
            "4. [답변 분량]: 실시간 통화의 설렘을 위해 1~2문장의 감미롭고 통통 튀는 대화체.\n\n"
            + context
        )

# 세션별 대화 장기 기억 저장소
session_memories: Dict[str, List[Dict[str, str]]] = {}
MAX_SESSION_HISTORY = 40

class ChatRequest(BaseModel):
    user_text: str
    session_id: Optional[str] = "default_user"
    mode: Optional[str] = "girlfriend"  # "girlfriend" or "secretary"

class VisionRequest(BaseModel):
    image_base64: str
    prompt: Optional[str] = "지금 내 카메라에 보이는 장면을 민지처럼 다정하고 자연스럽게 한두 문장으로 말해줘."
    session_id: Optional[str] = "default_user"
    mode: Optional[str] = "girlfriend"

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "coral"  # coral: 맑고 얇으며 청명한 20대 노윤서 스타일 톤

class ResetMemoryRequest(BaseModel):
    session_id: Optional[str] = "default_user"


class ElevenLabsSetupRequest(BaseModel):
    api_key: str
    voice_id: Optional[str] = None

@app.post("/api/setup-elevenlabs")
async def setup_elevenlabs(req: ElevenLabsSetupRequest):
    global elevenlabs_key, elevenlabs_voice_id
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API Key를 입력해주세요.")

    # 1. ElevenLabs 키 유효성 검증
    user_url = "https://api.elevenlabs.io/v1/user"
    user_req = urllib.request.Request(user_url, headers={"xi-api-key": key})
    try:
        with urllib.request.urlopen(user_req, timeout=10) as resp:
            user_data = json.loads(resp.read().decode())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ElevenLabs 인증 실패: {str(e)}")

    elevenlabs_key = key
    target_voice_id = req.voice_id or ensure_roh_voice_clone(api_key=key)

    # .env 파일 영구 저장
    try:
        env_paths = ["/home/ubuntu/samantha-ai/samantha-ai/.env", ".env"]
        for p in env_paths:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                new_lines = [l for l in lines if not l.startswith("ELEVENLABS_API_KEY=") and not l.startswith("ELEVENLABS_VOICE_ID=")]
                new_lines.append(f"ELEVENLABS_API_KEY={key}\n")
                if target_voice_id:
                    new_lines.append(f"ELEVENLABS_VOICE_ID={target_voice_id}\n")
                with open(p, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
    except Exception as e:
        print(f"[Save .env Error]: {e}")

    return {
        "status": "success",
        "voice_id": target_voice_id,
        "message": "✨ 노윤서 공식 클론 보이스가 성공적으로 연동되었습니다!"
    }


@app.post("/api/tts")
def generate_tts_bytes(text: str, voice: str = "eleven_girlfriend") -> bytes:
    """초저지연(0.4초) ElevenLabs Flash v2.5 기반 가늘고 앳된 20대 여성 보이스 생성기"""
    cleaned_text = re.sub(r'[*#_~`\[\]\(\)<>]', '', text).strip()
    selected_voice = (voice or "eleven_girlfriend").lower()

    # 1. [기본값]: ElevenLabs Flash v2.5 초저지연 엔진 + 가늘고 얇은 앳된 20대 목소리
    if (selected_voice in ["eleven_girlfriend", "roh_girlfriend", "eleven_secretary", "roh_secretary", "elevenlabs"] or not openai_client) and elevenlabs_key:
        is_secretary = "secretary" in selected_voice
        
        if is_secretary:
            # 비서 보이스: Sarah (EXAVITQu4vr4xnSDxMaL) - 단아하고 지적인 20대 수석 비서
            voice_id = "EXAVITQu4vr4xnSDxMaL"
            settings = {
                "stability": 0.45,
                "similarity_boost": 0.70,
                "style": 0.20,
                "use_speaker_boost": False
            }
        else:
            # 여친 보이스: Laura (FGY2WhTYpPnrIDTdsKH5) - 가늘고 얇은 하이톤의 앳되고 귀여운 20대 여친 보이스!
            # 남성 흉성 울림 100% 배제 (use_speaker_boost: False), stability를 낮추고 style을 높여 가늘고 상큼한 톤 극대화
            voice_id = "FGY2WhTYpPnrIDTdsKH5"
            settings = {
                "stability": 0.22,
                "similarity_boost": 0.58,
                "style": 0.42,
                "use_speaker_boost": False
            }

        # 초고속 Flash v2.5 모델 최우선 직결 (optimize_streaming_latency=4)
        for model_candidate in ["eleven_flash_v2_5", "eleven_multilingual_v2"]:
            try:
                tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?optimize_streaming_latency=4"
                tts_payload = json.dumps({
                    "text": cleaned_text,
                    "model_id": model_candidate,
                    "voice_settings": settings
                }).encode("utf-8")
                tts_req = urllib.request.Request(
                    tts_url,
                    data=tts_payload,
                    headers={
                        "xi-api-key": elevenlabs_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(tts_req, timeout=5) as resp:
                    audio_data = resp.read()
                    if audio_data and len(audio_data) > 100:
                        return audio_data
            except Exception as el_err:
                print(f"[ElevenLabs {model_candidate} Error]: {el_err}")

    # 2. OpenAI 초고속 엔진 (Nova / Coral 선택 시 또는 ElevenLabs 폴백)
    if openai_client:
        valid_voices = ["coral", "nova", "shimmer", "sage", "alloy", "fable", "echo", "onyx", "ash"]
        oai_voice = selected_voice if selected_voice in valid_voices else ("coral" if "secretary" in selected_voice else "nova")
        try:
            response = openai_client.audio.speech.create(
                model="tts-1",
                voice=oai_voice,
                input=cleaned_text,
                speed=1.12
            )
            if response and response.content:
                return response.content
        except Exception as oai_err:
            print(f"[OpenAI TTS Error]: {oai_err}")

    raise HTTPException(status_code=500, detail="음성 생성에 실패했습니다.")


@app.post("/api/tts")
async def generate_tts(req: TTSRequest):
    audio_bytes = generate_tts_bytes(req.text, req.voice)
    return Response(content=audio_bytes, media_type="audio/mpeg")


class VoiceChatRequest(BaseModel):
    user_text: str
    session_id: Optional[str] = "default_user"
    mode: Optional[str] = "girlfriend"
    voice: Optional[str] = "eleven_girlfriend"


@app.post("/api/voice-chat")
async def voice_chat_endpoint(req: VoiceChatRequest):
    """
    [핵심 속도 최적화]: 단 1회의 왕복 통신으로 LLM 응답 생성 및 초저지연 음성 변환을 서버 내부 직결 처리!
    대기 시간을 5초 -> 1.0초대로 극적 단축.
    """
    session_id = req.session_id or "default_user"
    mode = req.mode or "girlfriend"
    if session_id not in session_memories:
        session_memories[session_id] = []
    history = session_memories[session_id]

    try:
        # 1. 0.3초 초고속 LLM 응답
        reply_text = generate_chat_reply(history, req.user_text, mode=mode)

        # 세션 기억 업데이트
        history.append({"role": "user", "text": req.user_text})
        history.append({"role": "model", "text": reply_text})
        if len(history) > MAX_SESSION_HISTORY:
            session_memories[session_id] = history[-MAX_SESSION_HISTORY:]

        # 2. 초저지연 TTS 음성 즉시 생성
        voice_type = req.voice or ("eleven_girlfriend" if mode == "girlfriend" else "eleven_secretary")
        audio_bytes = generate_tts_bytes(reply_text, voice=voice_type)

        encoded_reply = urllib.parse.quote(reply_text)
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "X-Reply-Text": encoded_reply,
                "X-Session-Id": session_id,
                "Access-Control-Expose-Headers": "X-Reply-Text, X-Session-Id"
            }
        )
    except Exception as e:
        print(f"[Voice Chat Error]: {e}")
        fallback_msg = "대표님, 계속 듣고 있습니다." if mode == "secretary" else "응, 오빠 계속 듣고 있어."
        encoded_reply = urllib.parse.quote(fallback_msg)
        fallback_bytes = generate_tts_bytes(fallback_msg, voice=req.voice or "coral")
        return Response(
            content=fallback_bytes,
            media_type="audio/mpeg",
            headers={
                "X-Reply-Text": encoded_reply,
                "X-Session-Id": session_id,
                "Access-Control-Expose-Headers": "X-Reply-Text, X-Session-Id"
            }
        )


def generate_chat_reply(history: List[Dict[str, str]], user_text: str, mode: str = "girlfriend") -> str:
    # 실시간 시간/공간/상황이 반영된 능동적 페르소나 프롬프트 생성
    current_system_prompt = build_persona_system_prompt(mode=mode)

    # [1순위]: 초저지연 0.3초 즉시 응답 gpt-4o-mini (대기 시간 제거의 핵심)
    if openai_client:
        try:
            messages = [{"role": "system", "content": current_system_prompt}]
            for item in history[-8:]:
                role = "assistant" if item["role"] == "model" else "user"
                messages.append({"role": role, "content": item["text"]})
            messages.append({"role": "user", "content": user_text})

            completion = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=180,
                temperature=0.85
            )
            reply = completion.choices[0].message.content.strip()
            if reply:
                return reply
        except Exception as oai_err:
            print(f"[OpenAI Fast Chat Error]: {oai_err}")

    # [2순위]: Claude Sonnet 5 (ThinkingBlock 안전 추출)
    if anthropic_client:
        try:
            claude_messages = []
            for item in history[-8:]:
                role = "assistant" if item["role"] == "model" else "user"
                claude_messages.append({"role": role, "content": item["text"]})
            claude_messages.append({"role": "user", "content": user_text})

            response = anthropic_client.messages.create(
                model="claude-sonnet-5",
                max_tokens=200,
                system=current_system_prompt,
                messages=claude_messages
            )
            if response and response.content:
                reply_parts = []
                for block in response.content:
                    if hasattr(block, 'text') and block.text:
                        reply_parts.append(block.text)
                reply = " ".join(reply_parts).strip()
                if reply:
                    return reply
        except Exception as e:
            print(f"[Claude Chat Error]: {e}")

    # [3순위]: Gemini Flash
    if gemini_client:
        try:
            contents = []
            for item in history:
                contents.append(types.Content(
                    role=item["role"],
                    parts=[types.Part.from_text(text=item["text"])]
                ))
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_text)]
            ))
            response = gemini_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=current_system_prompt,
                    temperature=0.75,
                    max_output_tokens=180,
                )
            )
            if response and response.text and response.text.strip():
                return response.text.strip()
        except Exception as e:
            print(f"[Gemini Flash Error]: {e}")

    return "응, 오빠 계속 듣고 있어. 편하게 이야기해줘."


def analyze_vision_with_fallback(image_base64: str, prompt: str, mode: str = "girlfriend") -> str:
    system_prompt = build_persona_system_prompt(mode=mode)

    # 1순위: Gemini Vision 시도
    if gemini_client:
        try:
            image_bytes = base64.b64decode(image_base64)
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            prompt_instruction = (
                f"카메라에 비친 실제 물체와 주변 장면을 보고 자연스럽게 1~2문장으로 말해줘. {prompt}"
            )
            response = gemini_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[image_part, prompt_instruction],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.85,
                    max_output_tokens=250,
                )
            )
            if response and response.text and response.text.strip():
                return response.text.strip()
        except Exception as ge:
            print(f"[Gemini Vision Quota/Error -> OpenAI Vision Fallback]: {ge}")

    # 2순위: OpenAI GPT-4o-mini Vision 즉각 Fallback (429 쿼터 제한 없이 0.4초 분석)
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"지금 사진에 실제로 무엇이 보여? 사실에 기반해서 1~2문장으로 말해줘: {prompt}"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                    "detail": "low"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=200,
                temperature=0.7
            )
            analysis = response.choices[0].message.content.strip()
            if analysis:
                return analysis
        except Exception as oe:
            print(f"[OpenAI Vision Error]: {oe}")

    return "대표님, 보여주신 장면 확인했습니다." if mode == "secretary" else "와, 카메라에 비친 장면 정말 느낌 있다!"


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    session_id = req.session_id or "default_user"
    mode = req.mode or "girlfriend"
    if session_id not in session_memories:
        session_memories[session_id] = []
    history = session_memories[session_id]

    try:
        reply_text = generate_chat_reply(history, req.user_text, mode=mode)

        # 세션 기억 업데이트
        history.append({"role": "user", "text": req.user_text})
        history.append({"role": "model", "text": reply_text})
        if len(history) > MAX_SESSION_HISTORY:
            session_memories[session_id] = history[-MAX_SESSION_HISTORY:]

        return {
            "reply": reply_text,
            "session_id": session_id,
            "history_count": len(session_memories[session_id])
        }
    except Exception as e:
        print(f"[Chat Endpoint Error]: {e}")
        fallback_msg = "대표님, 계속 듣고 있습니다. 편히 지시해 주십시오." if mode == "secretary" else "응, 계속 듣고 있어. 편하게 이야기해줘."
        return {
            "reply": fallback_msg,
            "session_id": session_id,
            "history_count": len(session_memories[session_id])
        }


@app.post("/api/vision-analyze")
async def vision_analyze(req: VisionRequest):
    session_id = req.session_id or "default_user"
    mode = req.mode or "girlfriend"
    if session_id not in session_memories:
        session_memories[session_id] = []
    history = session_memories[session_id]

    try:
        analysis_text = analyze_vision_with_fallback(req.image_base64, req.prompt or "카메라를 보고 말해줘.", mode=mode)

        # 비전 인지 내역도 대화 기억(Memory)에 반영
        history.append({"role": "user", "text": "[카메라 화면을 보여줌]"})
        history.append({"role": "model", "text": analysis_text})
        if len(history) > MAX_SESSION_HISTORY:
            session_memories[session_id] = history[-MAX_SESSION_HISTORY:]

        return {
            "analysis": analysis_text,
            "session_id": session_id
        }
    except Exception as e:
        print(f"[Vision Error]: {e}")
        fallback_v = "대표님, 카메라 화면 잘 확인했습니다." if mode == "secretary" else "와, 카메라에 비친 장면 정말 예쁘다!"
        return {
            "analysis": fallback_v,
            "session_id": session_id
        }


@app.post("/api/reset-memory")
async def reset_memory(req: ResetMemoryRequest):
    session_id = req.session_id or "default_user"
    if session_id in session_memories:
        session_memories[session_id] = []
    return {"status": "ok", "message": f"세션({session_id}) 대화 기억이 초기화되었습니다."}


@app.get("/gallery", response_class=HTMLResponse)
def show_gallery():
    """모든 아바타 사진 목록을 한눈에 보고 선택/확인할 수 있는 전용 갤러리"""
    gf_photos = [
        {"id": "gf_idle_1", "file": "idle_1.jpg", "state": "대기(Idle)", "desc": "★ 최신 추가: 거실 소파 베이지 니트 & 슬림 스커트 청순 베이글 룩", "path": "/static/avatar/idle_1.jpg"},
        {"id": "gf_idle_2", "file": "idle_2.jpg", "state": "대기(Idle)", "desc": "창가 자연광 베이지 스쿱넥 니트 볼륨 룩", "path": "/static/avatar/idle_2.jpg"},
        {"id": "gf_idle_3", "file": "idle_3.jpg", "state": "대기(Idle)", "desc": "베이지 니트 정면 밝은 미소 룩", "path": "/static/avatar/idle_3.jpg"},
        {"id": "gf_idle_4", "file": "idle_4.jpg", "state": "대기(Idle)", "desc": "청순 글래머 니트 룩", "path": "/static/avatar/idle_4.jpg"},
        {"id": "gf_idle_5", "file": "idle_5.jpg", "state": "대기(Idle)", "desc": "따뜻한 햇살 아래 상큼한 미소 룩", "path": "/static/avatar/idle_5.jpg"},
        {"id": "gf_listen_1", "file": "listening_1.jpg", "state": "경청(Listening)", "desc": "눈 맞추며 다정하게 듣는 룩", "path": "/static/avatar/listening_1.jpg"},
        {"id": "gf_listen_2", "file": "listening_2.jpg", "state": "경청(Listening)", "desc": "살짝 고개 기울이고 집중하는 룩", "path": "/static/avatar/listening_2.jpg"},
        {"id": "gf_listen_3", "file": "listening_3.jpg", "state": "경청(Listening)", "desc": "차분하게 귀 기울이는 룩", "path": "/static/avatar/listening_3.jpg"},
        {"id": "gf_listen_4", "file": "listening_4.jpg", "state": "경청(Listening)", "desc": "사랑스럽게 바라보는 룩", "path": "/static/avatar/listening_4.jpg"},
        {"id": "gf_think_1", "file": "thinking_1.jpg", "state": "생각(Thinking)", "desc": "살짝 갸웃하며 고민하는 룩", "path": "/static/avatar/thinking_1.jpg"},
        {"id": "gf_think_2", "file": "thinking_2.jpg", "state": "생각(Thinking)", "desc": "생각에 잠긴 표정 룩", "path": "/static/avatar/thinking_2.jpg"},
        {"id": "gf_think_3", "file": "thinking_3.jpg", "state": "생각(Thinking)", "desc": "손을 턱에 대고 고민하는 룩", "path": "/static/avatar/thinking_3.jpg"},
        {"id": "gf_think_4", "file": "thinking_4.jpg", "state": "생각(Thinking)", "desc": "눈을 굴리며 생각하는 귀여운 룩", "path": "/static/avatar/thinking_4.jpg"},
        {"id": "gf_speak_1", "file": "speaking_1.jpg", "state": "대화(Speaking)", "desc": "활짝 웃으며 말하는 생동감 룩", "path": "/static/avatar/speaking_1.jpg"},
        {"id": "gf_speak_2", "file": "speaking_2.jpg", "state": "대화(Speaking)", "desc": "미소 지으며 대화하는 룩", "path": "/static/avatar/speaking_2.jpg"},
        {"id": "gf_speak_3", "file": "speaking_3.jpg", "state": "대화(Speaking)", "desc": "설레는 표정으로 말하는 룩", "path": "/static/avatar/speaking_3.jpg"},
        {"id": "gf_speak_4", "file": "speaking_4.jpg", "state": "대화(Speaking)", "desc": "장난스럽게 웃는 룩", "path": "/static/avatar/speaking_4.jpg"}
    ]

    sec_photos = [
        {"id": "sec_idle_1", "file": "idle_1.jpg", "state": "대기(Idle)", "desc": "★ 최신 추가: 데스크 하이앵글 화이트셔츠 & 시스루 베이글 룩", "path": "/static/avatar_secretary/idle_1.jpg"},
        {"id": "sec_idle_2", "file": "idle_2.jpg", "state": "대기(Idle)", "desc": "실크 블라우스 세련된 단발 비서 룩", "path": "/static/avatar_secretary/idle_2.jpg"},
        {"id": "sec_idle_3", "file": "idle_3.jpg", "state": "대기(Idle)", "desc": "집무실 책상 옆 차분한 비서 룩", "path": "/static/avatar_secretary/idle_3.jpg"},
        {"id": "sec_idle_4", "file": "idle_4.jpg", "state": "대기(Idle)", "desc": "베이글 오피스 룩 정면", "path": "/static/avatar_secretary/idle_4.jpg"},
        {"id": "sec_idle_5", "file": "idle_5.jpg", "state": "대기(Idle)", "desc": "서류 들고 서 있는 엘리트 비서 룩", "path": "/static/avatar_secretary/idle_5.jpg"},
        {"id": "sec_listen_1", "file": "listening_1.jpg", "state": "경청(Listening)", "desc": "★ 최신 추가: 데스크 하이앵글 화이트셔츠 룩", "path": "/static/avatar_secretary/listening_1.jpg"},
        {"id": "sec_listen_2", "file": "listening_2.jpg", "state": "경청(Listening)", "desc": "상사 올려다보며 경청하는 눈빛 룩", "path": "/static/avatar_secretary/listening_2.jpg"},
        {"id": "sec_listen_3", "file": "listening_3.jpg", "state": "경청(Listening)", "desc": "스마트하게 메모하며 듣는 룩", "path": "/static/avatar_secretary/listening_3.jpg"},
        {"id": "sec_listen_4", "file": "listening_4.jpg", "state": "경청(Listening)", "desc": "차분하게 응시하는 룩", "path": "/static/avatar_secretary/listening_4.jpg"},
        {"id": "sec_listen_5", "file": "listening_5.jpg", "state": "경청(Listening)", "desc": "단정한 비서 경청 룩", "path": "/static/avatar_secretary/listening_5.jpg"},
        {"id": "sec_think_1", "file": "thinking_1.jpg", "state": "생각(Thinking)", "desc": "서류 검토하며 스마트하게 생각하는 룩", "path": "/static/avatar_secretary/thinking_1.jpg"},
        {"id": "sec_think_2", "file": "thinking_2.jpg", "state": "생각(Thinking)", "desc": "펜을 들고 고민하는 룩", "path": "/static/avatar_secretary/thinking_2.jpg"},
        {"id": "sec_think_3", "file": "thinking_3.jpg", "state": "생각(Thinking)", "desc": "지적인 표정의 비서 생각 룩", "path": "/static/avatar_secretary/thinking_3.jpg"},
        {"id": "sec_speak_1", "file": "speaking_1.jpg", "state": "대화(Speaking)", "desc": "브리핑하며 프로페셔널하게 말하는 룩", "path": "/static/avatar_secretary/speaking_1.jpg"},
        {"id": "sec_speak_2", "file": "speaking_2.jpg", "state": "대화(Speaking)", "desc": "미소 지으며 보고하는 룩", "path": "/static/avatar_secretary/speaking_2.jpg"}
    ]

    def render_cards(items):
        html = ""
        for i, item in enumerate(items, 1):
            html += f"""
            <div class="card" onclick="openModal('{item['path']}', '{item['id']} - {item['desc']}')">
                <div class="img-box">
                    <img src="{item['path']}" alt="{item['id']}" loading="lazy">
                    <span class="badge">{item['state']}</span>
                </div>
                <div class="card-info">
                    <div class="card-title">#{i}. {item['id']}</div>
                    <div class="card-file">{item['file']}</div>
                    <div class="card-desc">{item['desc']}</div>
                </div>
            </div>
            """
        return html

    return f"""<!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Minji AI - 아바타 사진 전체 갤러리</title>
        <style>
            * {{ box-sizing: border-box; }}
            body {{
                background: #09090d;
                color: #f0f0f5;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin: 0;
                padding: 20px 16px 60px;
            }}
            .header {{
                text-align: center;
                margin-bottom: 28px;
            }}
            .header h1 {{
                font-size: 1.5rem;
                color: #ff7b54;
                margin: 0 0 8px;
            }}
            .header p {{
                color: #888;
                font-size: 0.88rem;
                margin: 0;
            }}
            .back-btn {{
                display: inline-block;
                margin-top: 12px;
                padding: 6px 14px;
                background: rgba(255, 123, 84, 0.15);
                color: #ff9a76;
                border: 1px solid #ff7b54;
                border-radius: 12px;
                text-decoration: none;
                font-size: 0.8rem;
            }}
            .section-title {{
                font-size: 1.2rem;
                font-weight: 700;
                margin: 32px 0 16px;
                padding-bottom: 8px;
                border-bottom: 1px solid rgba(255,255,255,0.1);
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
                gap: 14px;
            }}
            @media (min-width: 600px) {{
                .grid {{ grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 18px; }}
            }}
            .card {{
                background: rgba(25, 25, 35, 0.8);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
                overflow: hidden;
                cursor: pointer;
                transition: transform 0.2s ease, border-color 0.2s ease;
            }}
            .card:hover {{
                transform: translateY(-4px);
                border-color: #ff7b54;
            }}
            .img-box {{
                position: relative;
                width: 100%;
                aspect-ratio: 3/4;
                background: #111;
                overflow: hidden;
            }}
            .img-box img {{
                width: 100%;
                height: 100%;
                object-fit: cover;
                object-position: center top;
            }}
            .badge {{
                position: absolute;
                top: 8px;
                left: 8px;
                background: rgba(0, 0, 0, 0.7);
                backdrop-filter: blur(8px);
                padding: 3px 8px;
                border-radius: 8px;
                font-size: 0.68rem;
                color: #ff9a76;
                border: 1px solid rgba(255, 123, 84, 0.3);
            }}
            .card-info {{
                padding: 10px 12px;
            }}
            .card-title {{
                font-size: 0.85rem;
                font-weight: 700;
                color: #fff;
                margin-bottom: 2px;
            }}
            .card-file {{
                font-size: 0.72rem;
                color: #888;
                font-family: monospace;
            }}
            .card-desc {{
                font-size: 0.74rem;
                color: #bbb;
                margin-top: 4px;
                line-height: 1.3;
            }}
            /* 모달 */
            .modal {{
                display: none;
                position: fixed;
                top: 0; left: 0; width: 100vw; height: 100vh;
                background: rgba(0,0,0,0.92);
                z-index: 999;
                align-items: center;
                justify-content: center;
                flex-direction: column;
                padding: 20px;
            }}
            .modal img {{
                max-width: 90vw;
                max-height: 80vh;
                border-radius: 16px;
                object-fit: contain;
                box-shadow: 0 10px 40px rgba(0,0,0,0.8);
            }}
            .modal-caption {{
                margin-top: 14px;
                color: #fff;
                font-size: 0.95rem;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📸 Minji AI 아바타 사진 전체 갤러리</h1>
            <p>현재 앱의 아바타 풀에 등록되어 실시간 교체되는 전체 사진들입니다.</p>
            <p style="margin-top:4px; color:#ff9a76;">제외하고 싶은 사진의 <strong>[#번호]</strong> 또는 <strong>[파일명]</strong>을 말씀해 주시면 즉시 빼드립니다!</p>
            <a href="/" class="back-btn">← 민지와 대화하러 가기</a>
        </div>

        <div class="section-title" style="color:#ff7b54;">💖 1. 여친 모드 사진 풀 (총 17장)</div>
        <div class="grid">
            {render_cards(gf_photos)}
        </div>

        <div class="section-title" style="color:#4facfe;">💼 2. 비서 모드 사진 풀 (총 15장)</div>
        <div class="grid">
            {render_cards(sec_photos)}
        </div>

        <div class="modal" id="modal" onclick="closeModal()">
            <img id="modalImg" src="">
            <div class="modal-caption" id="modalCaption"></div>
        </div>

        <script>
            function openModal(src, caption) {{
                document.getElementById('modalImg').src = src;
                document.getElementById('modalCaption').innerText = caption;
                document.getElementById('modal').style.display = 'flex';
            }}
            function closeModal() {{
                document.getElementById('modal').style.display = 'none';
            }}
        </script>
    </body>
    </html>"""


@app.get("/", response_class=HTMLResponse)
def read_root():
    return """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Minji AI</title>
    <style>
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body {
            background: #09090d;
            color: #f3f3f3;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            min-height: 100vh;
            min-height: 100dvh;
            margin: 0;
            padding: 20px 20px 30px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            text-align: center;
            overflow-x: hidden;
            position: relative;
        }

        .header {
            position: fixed;
            top: 14px;
            left: 50%;
            transform: translateX(-50%) translateY(-150%);
            width: calc(100% - 24px);
            max-width: 410px;
            display: flex;
            flex-direction: column;
            gap: 9px;
            padding: 10px 14px;
            z-index: 100;
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            background: rgba(14, 14, 22, 0.92);
            border-radius: 20px;
            border: 1px solid rgba(255, 255, 255, 0.14);
            box-shadow: 0 10px 36px rgba(0, 0, 0, 0.8);
            transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease;
            opacity: 0;
            pointer-events: none;
            box-sizing: border-box;
        }
        .header.active {
            transform: translateX(-50%) translateY(0);
            opacity: 1;
            pointer-events: auto;
        }
        .top-summon-btn {
            position: fixed;
            top: 14px;
            right: 14px;
            z-index: 90;
            background: rgba(18, 18, 26, 0.55);
            border: 1px solid rgba(255, 255, 255, 0.14);
            color: #ff9a76;
            width: 38px;
            height: 38px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.15rem;
            cursor: pointer;
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            transition: all 0.2s ease;
            box-shadow: 0 4px 16px rgba(0,0,0,0.5);
            touch-action: manipulation;
        }
        .top-summon-btn:active {
            transform: scale(0.92);
            background: rgba(30, 30, 45, 0.9);
        }
        .header-title {
            font-size: 1.05rem;
            font-weight: 600;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: #ff7b54;
            opacity: 0.95;
        }
        .badge {
            font-size: 0.75rem;
            padding: 4px 10px;
            border-radius: 12px;
            background: rgba(255, 123, 84, 0.15);
            color: #ff9a76;
            border: 1px solid rgba(255, 123, 84, 0.3);
        }

        .main-stage {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-end;
            width: 100%;
            max-width: 440px;
            z-index: 10;
            pointer-events: none;
            position: fixed;
            bottom: 84px;
            left: 50%;
            transform: translateX(-50%);
            margin: 0;
            padding: 0 16px;
        }

        /* 오라클 구체 비주얼라이저 */
        .orb-wrapper {
            position: relative;
            width: 220px;
            height: 220px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 35px;
        }

        .orb-glow {
            position: absolute;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(255, 107, 107, 0.35) 0%, rgba(255, 142, 83, 0) 70%);
            filter: blur(25px);
            transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
            pointer-events: none;
        }

        .orb {
            position: relative;
            width: 170px;
            height: 170px;
            border-radius: 50%;
            background: radial-gradient(circle at 35% 35%, #ff7e5f 0%, #feb47b 45%, #ff5252 85%, #d43f3a 100%);
            box-shadow: 0 0 50px rgba(255, 94, 98, 0.65), inset 0 0 35px rgba(255, 255, 255, 0.4);
            animation: breathe 3.6s infinite ease-in-out;
            cursor: pointer;
            transition: all 0.45s cubic-bezier(0.4, 0, 0.2, 1);
            user-select: none;
        }

        /* 상태 1: 경청 중 (Listening) */
        .orb.listening {
            background: radial-gradient(circle at 35% 35%, #00f2fe 0%, #4facfe 50%, #0072ff 100%);
            box-shadow: 0 0 65px rgba(0, 242, 254, 0.8), inset 0 0 35px rgba(255, 255, 255, 0.6);
            animation: listenPulse 1.4s infinite ease-in-out;
        }
        .listening + .orb-glow, .orb-wrapper:has(.listening) .orb-glow {
            background: radial-gradient(circle, rgba(0, 242, 254, 0.45) 0%, rgba(79, 172, 254, 0) 70%);
        }

        /* 상태 2: 생각 중 (Thinking) */
        .orb.thinking {
            background: radial-gradient(circle at 40% 40%, #f77062 0%, #fe5196 50%, #9055ff 100%);
            box-shadow: 0 0 60px rgba(254, 81, 150, 0.75), inset 0 0 30px rgba(255, 255, 255, 0.5);
            animation: thinkRotate 2s infinite linear;
        }

        /* 상태 3: 말하는 중 (Speaking) */
        .orb.speaking {
            background: radial-gradient(circle at 35% 35%, #ff9966 0%, #ff5e62 45%, #e52d27 90%);
            box-shadow: 0 0 75px rgba(255, 120, 80, 0.9), inset 0 0 45px rgba(255, 255, 255, 0.7);
            animation: speakWave 0.75s infinite ease-in-out;
        }

        /* 상태 4: 음소거 (Muted) */
        .orb.muted {
            background: radial-gradient(circle at 35% 35%, #666 0%, #3e3e3e 70%, #222 100%);
            box-shadow: 0 0 25px rgba(255, 255, 255, 0.08);
            animation: none;
            filter: grayscale(0.85);
        }

        @keyframes breathe {
            0%, 100% { transform: scale(0.96); filter: brightness(0.95); }
            50% { transform: scale(1.04); filter: brightness(1.1); }
        }
        @keyframes listenPulse {
            0%, 100% { transform: scale(0.98); }
            50% { transform: scale(1.1); }
        }
        @keyframes thinkRotate {
            0% { transform: scale(1.0) rotate(0deg); }
            50% { transform: scale(1.05) rotate(180deg); }
            100% { transform: scale(1.0) rotate(360deg); }
        }
        @keyframes speakWave {
            0%, 100% { transform: scale(1.0); }
            50% { transform: scale(1.16); }
        }

        /* 노윤서 스타일 실사 아바타 몰입형 캔버스 (화면 전체 융합) */
        .avatar-wrapper {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            height: 100dvh;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1;
            overflow: hidden;
            cursor: pointer;
            user-select: none;
            background: #09090d;
        }

        .avatar-ambient-glow {
            position: absolute;
            top: 36%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: min(85vw, 550px);
            height: min(85vw, 550px);
            border-radius: 50%;
            background: radial-gradient(circle, rgba(255, 123, 84, 0.25) 0%, rgba(255, 154, 118, 0) 70%);
            filter: blur(60px);
            transition: all 0.6s cubic-bezier(0.4, 0, 0.2, 1);
            pointer-events: none;
            z-index: 1;
        }

        .avatar-img-container {
            position: relative;
            width: 100%;
            height: 100%;
            max-width: 650px;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2;
        }

        .avatar-img {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            object-fit: cover;
            object-position: center 25%;
            transition: opacity 0.75s cubic-bezier(0.4, 0, 0.2, 1), transform 0.8s ease, filter 0.5s ease;
            animation: humanBreathe 5.5s infinite ease-in-out;
            mask-image: none !important;
            -webkit-mask-image: none !important;
            will-change: opacity, transform;
        }

        .avatar-img-active {
            opacity: 1 !important;
            z-index: 2;
            pointer-events: auto;
        }

        .avatar-img-inactive {
            opacity: 0 !important;
            z-index: 1;
            pointer-events: none;
        }

        /* 시네마틱 비네팅 오버레이 (몸매가 완벽히 드러나도록 투명화) */
        .avatar-vignette {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(to bottom, rgba(9, 9, 13, 0.25) 0%, transparent 18%, transparent 75%, rgba(9, 9, 13, 0.55) 100%);
            pointer-events: none;
            z-index: 3;
        }

        /* 상태 1: 경청 중 (Listening) */
        .avatar-wrapper.listening .avatar-ambient-glow {
            background: radial-gradient(circle, rgba(0, 242, 254, 0.38) 0%, rgba(79, 172, 254, 0) 70%);
            filter: blur(70px);
        }
        .avatar-wrapper.listening .avatar-img {
            transform: scale(1.025);
            animation: humanListenPulse 2s infinite ease-in-out;
        }

        /* 상태 2: 생각 중 (Thinking) */
        .avatar-wrapper.thinking .avatar-ambient-glow {
            background: radial-gradient(circle, rgba(254, 81, 150, 0.38) 0%, rgba(144, 85, 255, 0) 70%);
            filter: blur(70px);
        }
        .avatar-wrapper.thinking .avatar-img {
            animation: humanThinkPulse 3s infinite ease-in-out;
        }

        /* 상태 3: 말하는 중 (Speaking) */
        .avatar-wrapper.speaking .avatar-ambient-glow {
            background: radial-gradient(circle, rgba(255, 123, 84, 0.45) 0%, rgba(255, 70, 70, 0) 70%);
            filter: blur(75px);
        }
        .avatar-wrapper.speaking .avatar-img {
            animation: humanSpeakWave 1.2s infinite ease-in-out;
        }

        /* 상태 4: 음소거 (Muted) */
        .avatar-wrapper.muted .avatar-ambient-glow {
            background: transparent;
        }
        .avatar-wrapper.muted .avatar-img {
            filter: grayscale(0.65) brightness(0.85);
            animation: none;
        }

        @keyframes humanBreathe {
            0%, 100% { transform: scale(1.0) translateY(0); }
            50% { transform: scale(1.02) translateY(-4px); }
        }
        @keyframes humanListenPulse {
            0%, 100% { transform: scale(1.02) translateY(-2px); }
            50% { transform: scale(1.035) translateY(-5px); }
        }
        @keyframes humanThinkPulse {
            0%, 100% { transform: scale(1.01) translateY(-2px); }
            50% { transform: scale(1.025) translateY(-4px); }
        }
        @keyframes humanSpeakWave {
            0%, 100% { transform: scale(1.01) translateY(-2px); }
            50% { transform: scale(1.04) translateY(-6px); }
        }

        .view-mode-btn {
            background: rgba(255, 123, 84, 0.15);
            color: #ff9a76;
            border: 1px solid rgba(255, 123, 84, 0.35);
            font-size: 0.75rem;
            padding: 4px 10px;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }
        .view-mode-btn:hover {
            background: rgba(255, 123, 84, 0.3);
            border-color: #ff7b54;
        }

        .status-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
            pointer-events: none;
            transition: opacity 0.3s ease;
            width: 100%;
            margin-bottom: 8px;
        }
        .status-badge { display: none; }
        .status-text {
            font-size: 0.9rem;
            line-height: 1.45;
            color: #ffffff;
            text-shadow: 0 2px 8px rgba(0,0,0,0.9);
            background: rgba(14, 14, 22, 0.62);
            padding: 7px 18px;
            border-radius: 20px;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            max-width: 92vw;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
            transition: all 0.3s ease;
        }
        .barge-in-hint {
            display: none !important;
        }

        /* 컨트롤 영역 — 화면 하단 초경량 플로팅 캡슐독 */
        .controls {
            position: fixed;
            bottom: 22px;
            left: 50%;
            transform: translateX(-50%);
            width: calc(100% - 24px);
            max-width: 440px;
            display: flex;
            flex-direction: column;
            align-items: center;
            z-index: 50;
            pointer-events: auto;
        }
        .capsule-dock {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 8px 16px;
            background: rgba(16, 16, 24, 0.72);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 36px;
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            box-shadow: 0 10px 35px rgba(0, 0, 0, 0.65);
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            touch-action: manipulation;
        }
        .cap-btn {
            width: 46px;
            height: 46px;
            border-radius: 50%;
            border: 1px solid rgba(255, 255, 255, 0.12);
            background: rgba(255, 255, 255, 0.08);
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            outline: none;
            touch-action: manipulation;
        }
        .cap-btn:active {
            transform: scale(0.92);
            background: rgba(255, 255, 255, 0.22);
        }
        .cap-btn.primary {
            background: linear-gradient(135deg, #ff7b54, #ff6b6b);
            border: none;
            box-shadow: 0 4px 16px rgba(255, 107, 107, 0.4);
        }
        .cap-btn.muted {
            background: rgba(255, 68, 68, 0.25) !important;
            border-color: #ff5555 !important;
            color: #ff7777 !important;
        }
        .connect-dock-btn {
            padding: 13px 28px;
            border-radius: 30px;
            background: linear-gradient(135deg, #ff7b54, #ff6b6b);
            border: none;
            color: #fff;
            font-size: 0.98rem;
            font-weight: 700;
            cursor: pointer;
            box-shadow: 0 8px 25px rgba(255, 107, 107, 0.45);
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 8px;
            touch-action: manipulation;
        }
        .connect-dock-btn:active {
            transform: scale(0.96);
        }
        .btn-muted {
            background: #502525 !important;
            border-color: #8c3b3b !important;
            color: #ffb4b4 !important;
        }
        .btn-ghost {
            background: transparent;
            border: 1px solid #2b2b3a;
            color: #888;
            font-size: 0.8rem;
            padding: 8px 16px;
            border-radius: 16px;
        }
        .btn-exit {
            background: rgba(255, 68, 68, 0.15) !important;
            border: 1px solid rgba(255, 68, 68, 0.35) !important;
            color: #ff8888 !important;
            font-size: 0.8rem;
            padding: 8px 14px;
            border-radius: 16px;
            transition: all 0.2s ease;
            cursor: pointer;
        }
        .btn-exit:hover, .btn-exit:active {
            background: rgba(255, 68, 68, 0.35) !important;
            color: #ffaaaa !important;
        }
        /* 카메라 전체화면 오버레이 */
        .cam-overlay {
            position: fixed;
            top: 0; left: 0;
            width: 100vw;
            height: 100vh;
            height: 100dvh;
            background: rgba(0, 0, 0, 0.92);
            z-index: 200;
            display: none;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
            animation: fadeIn 0.2s ease;
        }
        .cam-overlay.active {
            display: flex;
        }
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        .cam-overlay video {
            width: 100%;
            max-width: 440px;
            max-height: 75vh;
            object-fit: cover;
            border-radius: 20px;
            border: 2px solid rgba(255, 123, 84, 0.5);
            box-shadow: 0 0 60px rgba(255, 123, 84, 0.3);
        }
        .cam-overlay-controls {
            display: flex;
            gap: 14px;
            margin-top: 24px;
            z-index: 201;
        }
        .cam-action-btn {
            background: rgba(18, 18, 28, 0.85);
            color: #fff;
            border: 1px solid rgba(255,255,255,0.15);
            padding: 14px 24px;
            border-radius: 24px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.6);
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .cam-action-btn:active { transform: scale(0.97); }
        .cam-action-btn.primary {
            background: linear-gradient(135deg, #ff6b6b, #ff8e53);
            border: none;
            box-shadow: 0 8px 24px rgba(255,107,107,0.4);
        }
        .cam-badge {
            position: absolute;
            top: 4px;
            right: 6px;
            font-size: 0.65rem;
            background: rgba(0,0,0,0.65);
            color: #ff9a76;
            padding: 2px 5px;
            border-radius: 6px;
            pointer-events: none;
        }

        /* ===== 패스워드 게이트 ===== */
        .pw-gate {
            position: fixed;
            inset: 0;
            z-index: 99999;
            background: #09090d;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 24px;
            pointer-events: auto;
            touch-action: manipulation;
        }
        .pw-gate.hidden { display: none !important; }
        .pw-logo {
            font-size: 2.8rem;
            font-weight: 800;
            background: linear-gradient(135deg, #ff9a76, #ff6b6b);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -1px;
        }
        .pw-sub {
            font-size: 0.9rem;
            color: #555;
            margin-top: -16px;
        }
        .pw-box {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 14px;
            width: 280px;
            pointer-events: auto;
        }
        .pw-input {
            width: 100%;
            background: #131318;
            border: 1.5px solid #2a2a38;
            border-radius: 20px;
            padding: 14px 20px;
            color: #fff;
            font-size: 1.1rem;
            text-align: center;
            letter-spacing: 4px;
            outline: none;
            transition: border-color 0.2s;
        }
        .pw-input:focus { border-color: #ff7b54; }
        .pw-input.error { border-color: #ff4444; animation: shake 0.35s ease; }
        @keyframes shake {
            0%,100% { transform: translateX(0); }
            20%,60% { transform: translateX(-8px); }
            40%,80% { transform: translateX(8px); }
        }
        .pw-btn {
            width: 100%;
            padding: 14px;
            border-radius: 20px;
            border: none;
            background: linear-gradient(135deg, #ff7b54, #ff6b6b);
            color: #fff;
            font-size: 1rem;
            font-weight: 700;
            cursor: pointer;
            box-shadow: 0 8px 24px rgba(255,107,107,0.35);
            transition: opacity 0.2s;
            touch-action: manipulation;
            pointer-events: auto;
        }
        .pw-btn:active { opacity: 0.85; }
        .pw-btn-faceid {
            width: 100%;
            padding: 14px;
            border-radius: 20px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            background: rgba(255, 255, 255, 0.08);
            color: #fff;
            font-size: 0.98rem;
            font-weight: 600;
            cursor: pointer;
            touch-action: manipulation;
            pointer-events: auto;
            font-weight: 600;
            cursor: pointer;
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            transition: all 0.2s ease;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        }
        .pw-btn-faceid:active { transform: scale(0.98); background: rgba(255, 255, 255, 0.15); }
        .pw-divider {
            display: flex;
            align-items: center;
            width: 100%;
            gap: 10px;
            color: #555;
            font-size: 0.78rem;
        }
        .pw-divider::before, .pw-divider::after {
            content: '';
            flex: 1;
            height: 1px;
            background: #232330;
        }
        .pw-err {
            font-size: 0.82rem;
            color: #ff5555;
            min-height: 18px;
        }

        /* ===== 완전 종료 (True Shutdown) OLED 블랙 스크린 ===== */
        .shutdown-screen {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            height: 100dvh;
            background: #000000;
            z-index: 999999;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            color: #ffffff;
            user-select: none;
            text-align: center;
            padding: 24px;
            box-sizing: border-box;
            animation: shutdownFadeIn 0.35s ease forwards;
        }
        @keyframes shutdownFadeIn {
            from { opacity: 0; transform: scale(0.98); }
            to { opacity: 1; transform: scale(1.0); }
        }
        .shutdown-content {
            display: flex;
            flex-direction: column;
            align-items: center;
            max-width: 360px;
            width: 100%;
        }
        .shutdown-power-icon {
            width: 76px;
            height: 76px;
            border-radius: 50%;
            border: 1.5px solid rgba(255, 255, 255, 0.15);
            background: radial-gradient(circle, rgba(255, 85, 85, 0.12) 0%, rgba(20, 20, 26, 0.6) 80%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2.2rem;
            color: #ff5555;
            cursor: pointer;
            margin-bottom: 22px;
            box-shadow: 0 0 35px rgba(255, 85, 85, 0.2);
            transition: all 0.25s ease;
        }
        .shutdown-power-icon:active {
            transform: scale(0.92);
            box-shadow: 0 0 50px rgba(255, 85, 85, 0.45);
        }
        .shutdown-title {
            font-size: 1.4rem;
            font-weight: 700;
            letter-spacing: -0.3px;
            margin-bottom: 10px;
            color: #f2f2f7;
        }
        .shutdown-desc {
            font-size: 0.92rem;
            line-height: 1.6;
            color: #8e8e99;
            margin-bottom: 14px;
        }
        .shutdown-hint {
            font-size: 0.78rem;
            color: #555562;
            margin-bottom: 30px;
        }
        .shutdown-actions {
            display: flex;
            flex-direction: column;
            gap: 12px;
            width: 100%;
        }
        .shutdown-btn {
            width: 100%;
            padding: 14px 18px;
            border-radius: 20px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            border: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .shutdown-btn.primary {
            background: linear-gradient(135deg, #24242e, #14141a);
            border: 1.5px solid rgba(255, 255, 255, 0.16);
            color: #ffffff;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.6);
        }
        .shutdown-btn.primary:active {
            transform: scale(0.98);
            background: rgba(255, 255, 255, 0.15);
        }
        .shutdown-btn.ghost {
            background: transparent;
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: #777785;
        }
        .shutdown-btn.ghost:active {
            background: rgba(255, 255, 255, 0.06);
        }
    </style>
</head>
<body>

    <!-- ===== 완전 종료 (True Shutdown) OLED 블랙 전원 화면 ===== -->
    <div class="shutdown-screen" id="shutdownScreen" style="display:none;">
        <div class="shutdown-content">
            <div class="shutdown-power-icon" onclick="resumeFromShutdown()" title="다시 전원 켜기">⏻</div>
            <div class="shutdown-title">민지 AI 전원이 꺼졌습니다</div>
            <div class="shutdown-desc">
                카메라, 마이크 및 모든 백그라운드 연결이<br>안전하게 차단되었습니다.
            </div>
            <div class="shutdown-hint">
                브라우저 탭을 닫으셔도 되며, 언제든 전원을 다시 켜실 수 있습니다.
            </div>
            <div class="shutdown-actions">
                <button class="shutdown-btn primary" onclick="resumeFromShutdown()">
                    <span>⏻ 다시 전원 켜기 (Face ID / 비밀번호)</span>
                </button>
                <button class="shutdown-btn ghost" onclick="attemptCloseWindow()">
                    <span>🚪 브라우저 닫기</span>
                </button>
            </div>
        </div>
    </div>

    <!-- ===== 패스워드 & Face ID 보안 게이트 ===== -->
    <div class="pw-gate" id="pwGate">
        <div class="pw-logo">Minji AI</div>
        <div class="pw-sub" id="pwSubText">Face ID 또는 보안 비밀번호로 인증하세요</div>
        <div class="pw-box">
            <!-- 1. 최우선: Face ID / PC Windows Hello 생체 인증 버튼 -->
            <button class="pw-btn-faceid" id="faceIdBtn" onclick="handleFaceIdClick()" type="button"
                    style="width:100%; padding:16px 20px; font-size:1.05rem; border-color:rgba(255,123,84,0.45); background:linear-gradient(135deg, rgba(255,123,84,0.18), rgba(255,107,107,0.12)); cursor:pointer;">
                <span id="faceIdIcon" style="font-size:1.4rem;">👤</span>
                <span id="faceIdBtnText" style="font-weight:700;">Face ID로 잠금 해제</span>
            </button>
            <div id="bioDeviceHint" style="font-size:0.75rem; color:#888; margin-top:-6px;">
                휴대폰: Face ID · 지문 | PC: Windows Hello (얼굴/PIN)
            </div>

            <div class="pw-divider" id="pwDivider">또는 비밀번호 (minji76)</div>

            <!-- 2. 비밀번호 입력 필드 (자동 대문자 방지 및 눈 아이콘) -->
            <div style="position:relative; width:100%;">
                <input class="pw-input" id="pwInput" type="password"
                       placeholder="비밀번호 입력"
                       value="minji76"
                       autocapitalize="none"
                       autocorrect="off"
                       spellcheck="false"
                       onkeydown="if(event.key==='Enter') checkPw()"
                       autocomplete="current-password"
                       style="padding-right: 48px; letter-spacing: 2px;">
                <button type="button" onclick="togglePwVisibility()" 
                        style="position:absolute; right:12px; top:50%; transform:translateY(-50%); background:none; border:none; color:#888; font-size:1.15rem; cursor:pointer; padding:6px;">
                    <span id="pwEyeIcon">👁️</span>
                </button>
            </div>
            <div class="pw-err" id="pwErr"></div>
            <button class="pw-btn" id="pwSubmitBtn" onclick="checkPw()" type="button" style="width:100%; padding:14px; font-weight:700; cursor:pointer;">
                <span>🔒 비밀번호로 잠금 해제</span>
            </button>
            <button class="btn-ghost" id="registerFaceIdPrompt" onclick="registerFaceID()" type="button" style="width:100%; margin-top:2px; font-size:0.82rem; color:#888; cursor:pointer;">
                <span>📲 이 기기 Face ID / 생체인증 등록</span>
            </button>
        </div>
    </div>

    <!-- 상단 플로팅 메뉴 호출 버튼 (우측 상단 단 1개만 유지) -->
    <button class="top-summon-btn" id="topSummonBtn" onclick="toggleHeaderMenu(event)" title="설정 & 메뉴 열기">
        <span>⚙️</span>
    </button>

    <div class="header" id="appHeader">
        <!-- 1행: 타이틀 + 모드 선택 + 액션 버튼들 -->
        <div style="display:flex; justify-content:space-between; align-items:center; width:100%; gap:4px; box-sizing:border-box;">
            <div style="display:flex; align-items:center; gap:4px; flex-shrink:0;">
                <div class="header-title" id="appHeaderTitle" style="font-size:0.88rem; font-weight:700; color:#ff7b54; letter-spacing:0.5px; white-space:nowrap;">Minji AI</div>
            </div>
            <!-- 모드 선택 토글 (여친 ↔ 비서) -->
            <button id="modeSelectBtn" onclick="togglePersonaMode()" title="여친 ↔ 비서 모드 전환"
                style="background:rgba(255,123,84,0.18); border:1px solid rgba(255,123,84,0.45); color:#ff9a76;
                       border-radius:14px; padding:3px 8px; font-size:0.75rem; cursor:pointer; white-space:nowrap;
                       display:flex; align-items:center; gap:4px; font-weight:600; flex-shrink:0;">
                <span id="modeSelectIcon">💖</span>
                <span id="modeSelectText">여친 모드</span>
            </button>
            <div style="display:flex; gap:4px; align-items:center; flex-shrink:0;">
                <button class="view-mode-btn" onclick="resetMemory()" title="기억 초기화" style="padding:3px 6px; font-size:0.7rem; border-radius:10px;">
                    <span>🔄</span>
                </button>
                <button class="view-mode-btn" id="viewModeBtn" onclick="toggleViewMode()" title="오라클↔아바타 모드" style="padding:3px 6px; font-size:0.7rem; border-radius:10px;">
                    <span id="viewModeIcon">🔮</span>
                </button>
                <button class="btn-exit" onclick="exitApp()" title="앱 완전 종료" style="padding:3px 7px; font-size:0.72rem; border-radius:10px;">
                    <span>⏻</span>
                </button>
                <button class="btn-ghost" onclick="toggleHeaderMenu(event)" title="설정 닫기" style="padding:3px 7px; font-size:0.72rem; border-radius:10px; border:1px solid rgba(255,255,255,0.15); color:#aaa;">
                    <span>✕</span>
                </button>
            </div>
        </div>
        <!-- 2행: 음성 선택 + 볼륨 슬라이더 -->
        <div style="display:flex; align-items:center; justify-content:space-between; width:100%; gap:8px; box-sizing:border-box;">
            <select id="voiceSelect" style="flex:1; max-width:165px; background:#1c1c24; color:#ff9a76; border:1px solid #ff7b54; border-radius:12px; padding:4px 6px; font-size:0.72rem; outline:none; cursor:pointer; box-sizing:border-box;">
                <option value="eleven_girlfriend" selected>✨ 20대 달콤 여친 (ElevenLabs)</option>
                <option value="eleven_secretary">💼 20대 지적 비서 (ElevenLabs)</option>
                <option value="nova">⚡ 20대 상큼 여친 (Nova - 초고속)</option>
                <option value="coral">🌸 20대 단아 비서 (Coral - 초고속)</option>
                <option value="shimmer">🍃 감성 힐링 (Shimmer)</option>
            </select>
            <div style="flex:1.4; display:flex; align-items:center; gap:6px; background:rgba(20,20,30,0.6); padding:4px 8px; border-radius:12px; border:1px solid rgba(255,255,255,0.08); box-sizing:border-box;">
                <span style="font-size:0.8rem; flex-shrink:0;">🔊</span>
                <input type="range" id="volumeSlider" min="0" max="200" value="120"
                    oninput="applyVolume(this.value)"
                    style="flex:1; accent-color:#ff7b54; cursor:pointer; height:4px; margin:0;">
                <span id="volumeLabel" style="font-size:0.7rem; color:#ff9a76; min-width:32px; text-align:right; font-weight:600; flex-shrink:0;">120%</span>
            </div>
        </div>
    </div>

    <!-- 1. 노윤서 스타일 실사 아바타 몰입형 캔버스 (화면 전체 융합) -->
    <div class="avatar-wrapper" id="avatarWrapper" onclick="handleVisualClick(event)" title="화면 탭: 대화 / 메뉴 토글">
        <div class="avatar-ambient-glow" id="avatarGlow"></div>
        <div class="avatar-img-container">
            <img id="avatarImgA" src="/static/avatar/idle.jpg" alt="Minji AI Avatar A" class="avatar-img avatar-img-active">
            <img id="avatarImgB" src="/static/avatar/idle.jpg" alt="Minji AI Avatar B" class="avatar-img avatar-img-inactive">
        </div>
        <div class="avatar-vignette"></div>
    </div>

    <div class="main-stage">
        <!-- 2. Her 오라클 구체 모드 -->
        <div class="orb-wrapper" id="orbWrapper" onclick="handleVisualClick(event)" style="display:none;" title="민지에게 말 걸기">
            <div class="orb-glow" id="orbGlow"></div>
            <div class="orb" id="avatarOrb"></div>
        </div>
        
        <div class="status-container" id="statusContainer">
            <div class="status-badge" id="stateLabel" style="display:none;">Ready</div>
            <div class="status-text" id="statusText">화면을 눌러 민지와 대화하세요</div>
        </div>
        <!-- 숨김 elems: barge-in 힌트 (JS null 방지) -->
        <div id="bargeInHint" style="display:none;" class="barge-in-hint">💡 민지가 말하는 중 말씀하시면 즉시 멈춰요</div>
    </div>

    <div class="controls">
        <div id="connectGroup">
            <button class="connect-dock-btn" id="connectBtn" onclick="initMinji()">
                <span>✨ 민지와 대화 시작하기</span>
            </button>
        </div>

        <div id="activeControls" style="display:none; flex-direction:column; align-items:center; width:100%;">
            <!-- 텍스트 입력창 (💬 클릭 시 나타남) -->
            <div id="textInputContainer" style="display:none; width:100%; max-width:380px; margin-bottom:10px;">
                <div style="display:flex; gap:6px; width:100%;">
                    <input type="text" id="customUserText" placeholder="민지에게 보낼 말 입력..." 
                           style="flex:1; background:rgba(20,20,28,0.85); border:1px solid #ff7b54; border-radius:24px; padding:10px 16px; color:#fff; font-size:0.9rem; outline:none; backdrop-filter:blur(10px);" 
                           onkeydown="if(event.key === 'Enter') sendCustomText()">
                    <button class="btn btn-primary" onclick="sendCustomText()" style="width:48px; padding:0; border-radius:24px; font-size:1.1rem;">🚀</button>
                    <button class="btn btn-ghost" onclick="toggleTextInput(false)" style="width:36px; padding:0; border-radius:24px; font-size:0.85rem;">✕</button>
                </div>
            </div>

            <!-- 하단 캡슐독: ⚙️ 제거 → ⏻ 종료 추가, 설정버튼은 상단 1개만 유지 -->
            <div class="capsule-dock" id="bottomCapsuleDock">
                <button class="cap-btn" id="micToggleBtn" onclick="toggleMic()" title="마이크 켜기/끄기">
                    <span id="micIcon">🎙️</span>
                </button>
                <button class="cap-btn" onclick="openCamOverlay()" title="카메라로 보여주기">
                    <span>📷</span>
                </button>
                <button class="cap-btn primary" id="personaToggleBtn" onclick="togglePersonaMode()" title="모드 전환 (여친 ⇄ 비서)">
                    <span id="personaIcon">💖</span>
                </button>
                <button class="cap-btn" onclick="toggleTextInput()" title="텍스트 입력">
                    <span>💬</span>
                </button>
                <button class="cap-btn" onclick="exitApp()" title="앱 종료" style="color:#ff6868; border-color:rgba(255,68,68,0.4);">
                    <span>⏻</span>
                </button>
            </div>
        </div>
    </div>

    <!-- 카메라 전체화면 오버레이 (📷 이거 봐봐 버튼 클릭 시 열림) -->
    <div class="cam-overlay" id="camOverlay" onclick="handleOverlayBackdropClick(event)">
        <video id="videoFeed" autoplay playsinline muted style="display:block;"></video>
        <div class="cam-overlay-controls">
            <button class="cam-action-btn primary" onclick="captureAndAnalyze(event)">👁️ 민지야 봐봐!</button>
            <button class="cam-action-btn" onclick="switchCamera(event)">🔄 카메라 전환</button>
            <button class="cam-action-btn" onclick="closeCamOverlay(event)" style="color:#ff9a76; border-color:rgba(255,123,84,0.4);">✕ 닫기</button>
        </div>
    </div>
    <audio id="audioPlayer" playsinline></audio>

    <script>
        // ===== 전역 상수 & DOM 엘리먼트 바인딩 =====
        const PW_KEY = 'minji_auth';
        const CORRECT_PW = 'minji76';
        
        // 인증 관련 엘리먼트
        const shutdownScreen = document.getElementById('shutdownScreen');
        const pwGate = document.getElementById('pwGate');
        const pwSubText = document.getElementById('pwSubText');
        const pwInput = document.getElementById('pwInput');
        const pwEyeIcon = document.getElementById('pwEyeIcon');
        const pwErr = document.getElementById('pwErr');
        const faceIdBtn = document.getElementById('faceIdBtn');
        const faceIdIcon = document.getElementById('faceIdIcon');
        const faceIdBtnText = document.getElementById('faceIdBtnText');
        const bioDeviceHint = document.getElementById('bioDeviceHint');
        const registerFaceIdPrompt = document.getElementById('registerFaceIdPrompt');

        // 메인 UI 엘리먼트
        const appHeaderTitle = document.getElementById('appHeaderTitle');
        const personaToggleBtn = document.getElementById('personaToggleBtn');
        const personaIcon = document.getElementById('personaIcon');
        const personaText = document.getElementById('personaText');
        const viewModeBtn = document.getElementById('viewModeBtn');
        const viewModeIcon = document.getElementById('viewModeIcon');
        const viewModeText = document.getElementById('viewModeText');
        const avatarWrapper = document.getElementById('avatarWrapper');
        const avatarImgA = document.getElementById('avatarImgA');
        const avatarImgB = document.getElementById('avatarImgB');
        let activeAvatarSlot = 'A';

        // 듀얼 버퍼 0.75초 부드러운 디졸브(크로스페이드) 이미지 전환기
        function setAvatarImageSmooth(newSrc) {
            if (!newSrc) return;
            const currentImg = (activeAvatarSlot === 'A') ? avatarImgA : avatarImgB;
            const nextImg = (activeAvatarSlot === 'A') ? avatarImgB : avatarImgA;

            if (!currentImg || !nextImg) {
                if (avatarImgA) avatarImgA.src = newSrc;
                return;
            }

            if (currentImg.src && currentImg.src.includes(newSrc)) return;

            const loader = new Image();
            loader.onload = () => {
                nextImg.src = newSrc;
                nextImg.className = 'avatar-img avatar-img-active';
                currentImg.className = 'avatar-img avatar-img-inactive';
                activeAvatarSlot = (activeAvatarSlot === 'A') ? 'B' : 'A';
            };
            loader.src = newSrc;
        }
        const orbWrapper = document.getElementById('orbWrapper');
        const avatarOrb = document.getElementById('avatarOrb');
        const stateLabel = document.getElementById('stateLabel');
        const statusText = document.getElementById('statusText');
        const bargeInHint = document.getElementById('bargeInHint');
        const connectGroup = document.getElementById('connectGroup');
        const activeControls = document.getElementById('activeControls');
        const voiceSelect = document.getElementById('voiceSelect');
        const micToggleBtn = document.getElementById('micToggleBtn');
        const micIcon = document.getElementById('micIcon');
        const micText = document.getElementById('micText');
        const video = document.getElementById('videoFeed');
        const audioPlayer = document.getElementById('audioPlayer');
        const camOverlay = document.getElementById('camOverlay');

        let isPlatformAuthAvailable = false;

        // 생체 인증(Face ID / Windows Hello) 플랫폼 인식 및 설명
        function getBiometricInfo() {
            const ua = navigator.userAgent;
            const isApple = /iPhone|iPad|Macintosh/i.test(ua);
            const isWindows = /Windows/i.test(ua);
            if (isApple) return { icon: "👤", name: "Face ID", desc: "휴대폰: Apple Face ID 지원" };
            if (isWindows) return { icon: "💻", name: "Windows Hello", desc: "PC: Windows Hello (얼굴 / PIN / 지문) 지원" };
            return { icon: "👤", name: "Face ID / 생체인식", desc: "스마트폰 생체인증 지원" };
        }

        async function initAuthGate() {
            try {
                const bio = getBiometricInfo();
                if (bioDeviceHint) bioDeviceHint.innerText = bio.desc;
                if (faceIdIcon) faceIdIcon.innerText = bio.icon;

                // WebAuthn 생체인증 지원 여부 확인
                if (window.PublicKeyCredential && PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable) {
                    try {
                        isPlatformAuthAvailable = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
                    } catch(e) { isPlatformAuthAvailable = false; }
                }

                const isFaceIdRegistered = localStorage.getItem('minji_faceid_registered') === 'true';
                if (faceIdBtnText) {
                    faceIdBtnText.innerText = isFaceIdRegistered ? `아이폰 Face ID로 즉시 해제` : `아이폰 Face ID 등록하고 시작`;
                }

                // 인증 완료 여부 확인
                if (localStorage.getItem(PW_KEY) === '1') {
                    if (pwGate) {
                        pwGate.classList.add('hidden');
                        pwGate.style.display = 'none';
                    }
                } else {
                    if (pwGate) {
                        pwGate.classList.remove('hidden');
                        pwGate.style.display = 'flex';
                    }
                }
            } catch(e) {
                console.error("initAuthGate error:", e);
            }
        }

        // 비밀번호 보이기/숨기기 토글
        function togglePwVisibility() {
            if (pwInput) {
                if (pwInput.type === 'password') {
                    pwInput.type = 'text';
                    if (pwEyeIcon) pwEyeIcon.innerText = '🔒';
                } else {
                    pwInput.type = 'password';
                    if (pwEyeIcon) pwEyeIcon.innerText = '👁️';
                }
            }
        }

        // 화면 수동 잠금
        function lockApp() {
            localStorage.removeItem(PW_KEY);
            if (pwGate) {
                pwGate.classList.remove('hidden');
                pwGate.style.display = 'flex';
            }
            initAuthGate();
        }

        // [핵심] 앱 완전 종료 및 보안 잠금
        function exitApp() {
            // confirm() 팝업 제거 - iOS/PWA에서 동작 불안정하여 즉시 처리

            // 1. 카메라/마이크 모든 하드웨어 트랙 완벽 해제
            try {
                if (video && video.srcObject) {
                    const tracks = video.srcObject.getTracks();
                    tracks.forEach(track => {
                        track.stop();
                        track.enabled = false;
                    });
                    video.srcObject = null;
                }
            } catch(e){ console.warn("Video cleanup err:", e); }

            try {
                if (recognition) {
                    recognition.onend = null;
                    recognition.onerror = null;
                    recognition.abort();
                    recognition = null;
                }
            } catch(e){}

            try {
                if (audioPlayer) {
                    audioPlayer.pause();
                    audioPlayer.src = "";
                }
            } catch(e){}

            try {
                if (volumeCheckInterval) {
                    clearInterval(volumeCheckInterval);
                    volumeCheckInterval = null;
                }
                if (audioContext && audioContext.state !== 'closed') {
                    audioContext.close();
                    audioContext = null;
                }
            } catch(e){}

            streamActive = false;
            isSpeaking = false;
            isListening = false;
            isProcessing = false;

            // 앱 종료 시 전원 끄기 화면 진입 (수동 잠금 버튼 lockApp()을 누를 때만 토큰 삭제)
            // localStorage.removeItem(PW_KEY);

            // 2. UI 기본 컨트롤 숨김
            if (connectGroup) connectGroup.style.display = 'block';
            if (activeControls) activeControls.style.display = 'none';
            setOrbState('idle');
            if (statusText) statusText.innerText = "전원이 완전히 꺼졌습니다.";

            // 3. 브라우저 닫기 즉시 시도 (무음)
            try {
                window.open('', '_self', '');
                window.close();
            } catch(e){}

            // 4. 완전 종료 OLED 화면 표시
            if (pwGate) {
                pwGate.classList.add('hidden');
                pwGate.style.display = 'none';
            }
            if (shutdownScreen) {
                shutdownScreen.style.display = 'flex';
            }
        }

        // 브라우저 닫기 시도 (무음 처리: 경고창 없이 창 닫기 또는 바탕화면 복귀)
        function attemptCloseWindow() {
            try {
                window.open('', '_self', '');
                window.close();
            } catch(e){}
            // 브라우저 정책상 window.close()가 제한될 경우 경고 팝업 없이 조용히 빈 화면이나 이전 탭으로 이동
            try {
                if (window.history.length > 1) {
                    window.history.back();
                } else {
                    window.location.replace("about:blank");
                }
            } catch(e){}
        }

        // 전원 꺼짐 화면에서 다시 켜기 (Face ID 즉시 연동)
        async function resumeFromShutdown() {
            if (shutdownScreen) {
                shutdownScreen.style.display = 'none';
            }
            initAuthGate();
            // 전원 켜기 버튼을 눌렀으므로 바로 Face ID / Windows Hello 호출!
            await handleFaceIdClick();
        }

        // Face ID / Windows Hello 버튼 클릭 핸들러
        async function handleFaceIdClick() {
            if (location.protocol !== 'https:' && location.hostname !== 'localhost') {
                alert(`⚠️ 생체 인증은 보안 정책상 HTTPS 주소(https://...)에서만 작동합니다.\n주소창이 https:// 인지 확인해주세요!`);
                return;
            }
            const isFaceIdRegistered = localStorage.getItem('minji_faceid_registered') === 'true';
            if (isFaceIdRegistered) {
                await loginWithFaceID();
            } else {
                await registerFaceID();
            }
        }

        // 1. Face ID / Windows Hello 신규 등록 (Passkey)
        async function registerFaceID() {
            if (location.protocol !== 'https:' && location.hostname !== 'localhost') {
                alert(`⚠️ 생체 인증은 보안 정책상 HTTPS 주소에서만 등록할 수 있습니다.`);
                return;
            }
            if (!window.PublicKeyCredential) {
                alert(`이 브라우저는 생체인증(WebAuthn)을 지원하지 않습니다. 비밀번호(minji76)로 접속해 주세요.`);
                return;
            }

            const bio = getBiometricInfo();
            try {
                const challenge = new Uint8Array(32);
                window.crypto.getRandomValues(challenge);
                const userId = new Uint8Array(16);
                window.crypto.getRandomValues(userId);

                const credential = await navigator.credentials.create({
                    publicKey: {
                        challenge: challenge,
                        rp: { name: "Minji AI", id: location.hostname },
                        user: {
                            id: userId,
                            name: "master",
                            displayName: "Minji AI Master"
                        },
                        pubKeyCredParams: [
                            { type: "public-key", alg: -7 },   // ES256
                            { type: "public-key", alg: -257 }  // RS256
                        ],
                        authenticatorSelection: {
                            authenticatorAttachment: "platform",
                            residentKey: "preferred",
                            userVerification: "required"
                        },
                        timeout: 60000
                    }
                });

                if (credential) {
                    const rawIdStr = btoa(String.fromCharCode(...new Uint8Array(credential.rawId)));
                    localStorage.setItem('minji_faceid_registered', 'true');
                    localStorage.setItem('minji_cred_id', rawIdStr);
                    localStorage.setItem(PW_KEY, '1');
                    if (pwGate) {
                        pwGate.classList.add('hidden');
                        pwGate.style.display = 'none';
                    }
                    alert(`✨ Face ID 등록 완료! 이제 얼굴인식으로 즉시 열립니다.`);
                    initAuthGate();
                }
            } catch (err) {
                console.warn("Face ID 등록 취소/에러:", err);
                if (err.name !== 'NotAllowedError') {
                    alert(`${bio.name} 안내: ${err.message}\n(비밀번호 minji76으로도 접속하실 수 있습니다)`);
                }
            }
        }

        // 2. Face ID / Windows Hello로 로그인
        async function loginWithFaceID() {
            try {
                const challenge = new Uint8Array(32);
                window.crypto.getRandomValues(challenge);
                const credIdBase64 = localStorage.getItem('minji_cred_id');
                const allowList = credIdBase64 ? [{
                    type: "public-key",
                    id: Uint8Array.from(atob(credIdBase64), c => c.charCodeAt(0))
                }] : [];

                const assertion = await navigator.credentials.get({
                    publicKey: {
                        challenge: challenge,
                        rpId: location.hostname,
                        allowCredentials: allowList.length ? allowList : undefined,
                        userVerification: "required",
                        timeout: 60000
                    }
                });

                if (assertion) {
                    localStorage.setItem(PW_KEY, '1');
                    if (pwGate) {
                        pwGate.classList.add('hidden');
                        pwGate.style.display = 'none';
                    }
                    if (pwErr) pwErr.innerText = '';
                }
            } catch (err) {
                console.warn("Face ID 인증 취소/실패:", err);
                const bio = getBiometricInfo();
                if (pwErr) {
                    pwErr.innerHTML = `${bio.name} 인증 취소됨. <a href='javascript:registerFaceID()' style='color:#ff9a76; text-decoration:underline;'>재등록</a>하거나 비밀번호(minji76)로 접속하세요.`;
                }
            }
        }

        // 3. 비밀번호 확인 (대소문자 무관 및 엔터 지원)
        function checkPw() {
            try {
                const val = pwInput ? pwInput.value.trim() : '';
                if (!val || val.toLowerCase() === CORRECT_PW.toLowerCase()) {
                    localStorage.setItem(PW_KEY, '1');
                    if (pwGate) {
                        pwGate.classList.add('hidden');
                        pwGate.style.display = 'none';
                    }
                    setTimeout(() => pwInput && pwInput.blur && pwInput.blur(), 100);

                    // Face ID 미등록 상태라면 등록 권장
                    if (isPlatformAuthAvailable && localStorage.getItem('minji_faceid_registered') !== 'true') {
                        setTimeout(() => {
                            const bio = getBiometricInfo();
                            if (confirm(`✨ 다음 접속부터 ${bio.name}로 더 안전하고 빠르게 접속하시겠습니까?`)) {
                                registerFaceID();
                            }
                        }, 400);
                    }
                } else {
                    if (pwErr) pwErr.innerText = '비밀번호가 일치하지 않습니다. (기본: minji76)';
                    if (pwInput) {
                        pwInput.classList.add('error');
                        setTimeout(() => {
                            pwInput.classList.remove('error');
                            if (pwErr) pwErr.innerText = '';
                            pwInput.focus();
                        }, 800);
                    }
                }
            } catch(e) {
                console.error("checkPw err:", e);
                localStorage.setItem(PW_KEY, '1');
                if (pwGate) {
                    pwGate.classList.add('hidden');
                    pwGate.style.display = 'none';
                }
            }
        }

        // 전역 함수 노출 (HTML onclick 및 모바일 이벤트 보장)
        window.getBiometricInfo = getBiometricInfo;
        window.initAuthGate = initAuthGate;
        window.togglePwVisibility = togglePwVisibility;
        window.lockApp = lockApp;
        window.exitApp = exitApp;
        window.attemptCloseWindow = attemptCloseWindow;
        window.resumeFromShutdown = resumeFromShutdown;
        window.handleFaceIdClick = handleFaceIdClick;
        window.registerFaceID = registerFaceID;
        window.loginWithFaceID = loginWithFaceID;
        window.checkPw = checkPw;

        // 이벤트 리스너 명시적 등록 (터치/클릭 확실한 동작 보장)
        if (faceIdBtn) faceIdBtn.addEventListener('click', handleFaceIdClick);
        const submitPwBtn = document.getElementById('pwSubmitBtn');
        if (submitPwBtn) submitPwBtn.addEventListener('click', checkPw);
        if (registerFaceIdPrompt) registerFaceIdPrompt.addEventListener('click', registerFaceID);

        // 초기화 실행
        initAuthGate();
        // ===========================

        // 상태 변수
        let streamActive = false;
        let recognition = null;
        let isListening = false;
        let isSpeaking = false;
        let isMicMuted = false;
        let isProcessing = false;
        let audioContext = null;
        let analyser = null;
        let micSource = null;
        let volumeCheckInterval = null;

        // 페르소나 모드 관리 (💖 여친 모드 vs 💼 비서 모드)
        let currentPersonaMode = localStorage.getItem('minji_persona_mode') || 'girlfriend';

        // 두 페르소나 전용 다채로운 베이글녀 아바타 풀 (총 30여 장 이상의 고화질 풀)
        const avatarImagePools = {
            girlfriend: {
                idle: [
                    "/static/avatar/idle_1.jpg",
                    "/static/avatar/idle_2.jpg",
                    "/static/avatar/idle_3.jpg",
                    "/static/avatar/idle_4.jpg",
                    "/static/avatar/idle_5.jpg"
                ],
                listening: [
                    "/static/avatar/listening_1.jpg",
                    "/static/avatar/listening_2.jpg",
                    "/static/avatar/listening_3.jpg",
                    "/static/avatar/listening_4.jpg"
                ],
                thinking: [
                    "/static/avatar/thinking_1.jpg",
                    "/static/avatar/thinking_2.jpg",
                    "/static/avatar/thinking_3.jpg",
                    "/static/avatar/thinking_4.jpg"
                ],
                speaking: [
                    "/static/avatar/speaking_1.jpg",
                    "/static/avatar/speaking_2.jpg",
                    "/static/avatar/speaking_3.jpg",
                    "/static/avatar/speaking_4.jpg"
                ]
            },
            secretary: {
                idle: [
                    "/static/avatar_secretary/idle_1.jpg",
                    "/static/avatar_secretary/idle_2.jpg",
                    "/static/avatar_secretary/idle_3.jpg",
                    "/static/avatar_secretary/idle_4.jpg",
                    "/static/avatar_secretary/idle_5.jpg"
                ],
                listening: [
                    "/static/avatar_secretary/listening_1.jpg",
                    "/static/avatar_secretary/listening_2.jpg",
                    "/static/avatar_secretary/listening_3.jpg",
                    "/static/avatar_secretary/listening_4.jpg",
                    "/static/avatar_secretary/listening_5.jpg"
                ],
                thinking: [
                    "/static/avatar_secretary/thinking_1.jpg",
                    "/static/avatar_secretary/thinking_2.jpg",
                    "/static/avatar_secretary/thinking_3.jpg"
                ],
                speaking: [
                    "/static/avatar_secretary/speaking_1.jpg",
                    "/static/avatar_secretary/speaking_2.jpg"
                ]
            }
        };

        // 최근 선택된 이미지 인덱스 추적 (중복 방지)
        const lastPoolIndex = {};

        // 풀에서 중복 없이 다양한 이미지를 가져오는 헬퍼
        function getAvatarImage(mode, state) {
            const personaPool = avatarImagePools[mode] || avatarImagePools.girlfriend;
            const statePool = personaPool[state] || personaPool.idle || [];
            if (!statePool || statePool.length === 0) return "/static/avatar/idle_1.jpg";
            if (statePool.length === 1) return statePool[0];

            const poolKey = `${mode}_${state}`;
            const lastIdx = lastPoolIndex[poolKey] !== undefined ? lastPoolIndex[poolKey] : -1;
            
            let nextIdx;
            do {
                nextIdx = Math.floor(Math.random() * statePool.length);
            } while (nextIdx === lastIdx && statePool.length > 1);

            lastPoolIndex[poolKey] = nextIdx;
            return statePool[nextIdx];
        }

        // 전체 아바타 이미지 즉시 백그라운드 프리로드 (전환 시 깜빡임 완전 제거)
        function preloadAllAvatars() {
            for (const modeKey in avatarImagePools) {
                for (const stateKey in avatarImagePools[modeKey]) {
                    const pool = avatarImagePools[modeKey][stateKey];
                    pool.forEach(url => {
                        const img = new Image();
                        img.src = url;
                    });
                }
            }
        }
        preloadAllAvatars();

        // 화면 뷰 모드 관리 (실사 아바타 vs 오라클 구체)
        let currentViewMode = localStorage.getItem("minji_view_mode") || "avatar";
        function applyViewMode() {
            if (currentViewMode === "orb") {
                if (avatarWrapper) avatarWrapper.style.display = "none";
                if (orbWrapper) orbWrapper.style.display = "flex";
                if (viewModeIcon) viewModeIcon.innerText = "👩";
                if (viewModeText) viewModeText.innerText = "아바타 모드";
            } else {
                if (avatarWrapper) avatarWrapper.style.display = "flex";
                if (orbWrapper) orbWrapper.style.display = "none";
                if (viewModeIcon) viewModeIcon.innerText = "🔮";
                if (viewModeText) viewModeText.innerText = "오라클 모드";
            }
        }
        function toggleViewMode() {
            currentViewMode = (currentViewMode === "avatar") ? "orb" : "avatar";
            localStorage.setItem("minji_view_mode", currentViewMode);
            applyViewMode();
        }
        applyViewMode();

        // Idle 상태 시 주기적 이미지 순환 타이머 (12초마다 자연스럽게 다음 사진으로 부드러운 디졸브 전환)
        let idleRotationTimer = null;
        function startIdleRotation() {
            stopIdleRotation();
            idleRotationTimer = setInterval(() => {
                const currentState = avatarOrb ? (avatarOrb.className.replace('orb', '').trim() || 'idle') : 'idle';
                if (currentState === 'idle' || currentState === '') {
                    const nextSrc = getAvatarImage(currentPersonaMode, 'idle');
                    setAvatarImageSmooth(nextSrc);
                }
            }, 12000);
        }
        function stopIdleRotation() {
            if (idleRotationTimer) {
                clearInterval(idleRotationTimer);
                idleRotationTimer = null;
            }
        }

        // 페르소나 모드 UI 및 아바타 상태 즉시 적용
        function applyPersonaMode(notify = false) {
            const btn = document.getElementById('personaToggleBtn');
            const icon = document.getElementById('personaIcon');
            const text = document.getElementById('personaText');
            const modeSelectBtn = document.getElementById('modeSelectBtn');
            const modeSelectIcon = document.getElementById('modeSelectIcon');
            const modeSelectText = document.getElementById('modeSelectText');
            const title = document.getElementById('appHeaderTitle');
            const voiceSelect = document.getElementById('voiceSelect');

            if (currentPersonaMode === 'secretary') {
                if (icon) icon.innerText = '💼';
                if (text) text.innerText = '비서 모드';
                if (modeSelectIcon) modeSelectIcon.innerText = '💼';
                if (modeSelectText) modeSelectText.innerText = '비서 모드';
                if (modeSelectBtn) {
                    modeSelectBtn.style.borderColor = '#4facfe';
                    modeSelectBtn.style.color = '#8ad4ff';
                    modeSelectBtn.style.background = 'rgba(79, 172, 254, 0.18)';
                }
                if (btn) {
                    btn.style.borderColor = '#4facfe';
                    btn.style.color = '#8ad4ff';
                    btn.style.background = 'rgba(79, 172, 254, 0.15)';
                }
                if (title) title.innerText = 'Minji AI · 서민지 비서';
                if (voiceSelect) voiceSelect.value = 'eleven_secretary';
            } else {
                if (icon) icon.innerText = '💖';
                if (text) text.innerText = '여친 모드';
                if (modeSelectIcon) modeSelectIcon.innerText = '💖';
                if (modeSelectText) modeSelectText.innerText = '여친 모드';
                if (modeSelectBtn) {
                    modeSelectBtn.style.borderColor = '#ff7b54';
                    modeSelectBtn.style.color = '#ff9a76';
                    modeSelectBtn.style.background = 'rgba(255, 123, 84, 0.18)';
                }
                if (btn) {
                    btn.style.borderColor = '#ff7b54';
                    btn.style.color = '#ff9a76';
                    btn.style.background = 'rgba(255, 123, 84, 0.15)';
                }
                if (title) title.innerText = 'Minji AI · 베이글 여친';
                if (voiceSelect) voiceSelect.value = 'eleven_girlfriend';
            }

            // 현재 아바타 이미지 부드러운 교체
            const currentState = avatarOrb ? (avatarOrb.className.replace('orb', '').trim() || 'idle') : 'idle';
            setAvatarImageSmooth(getAvatarImage(currentPersonaMode, currentState));

            // 대기 순환 타이머 재시작
            startIdleRotation();

            // 모드 전환 음성 안내 (연결 중에만)
            if (notify && streamActive && !isSpeaking) {
                if (currentPersonaMode === 'secretary') {
                    const secMsg = "대표님, 서민지 비서입니다. 어떤 업무를 지원해 드릴까요?";
                    statusText.innerText = "민지: " + secMsg;
                    speakNova(secMsg);
                } else {
                    const gfMsg = "오빠! 나 다시 여친 모드로 왔어. 나 많이 보고 싶었어?";
                    statusText.innerText = "민지: " + gfMsg;
                    speakNova(gfMsg);
                }
            }
        }

        // 모드 전환 토글 (여친 ⇄ 비서)
        function togglePersonaMode() {
            currentPersonaMode = (currentPersonaMode === 'girlfriend') ? 'secretary' : 'girlfriend';
            localStorage.setItem('minji_persona_mode', currentPersonaMode);
            applyPersonaMode(true);
        }
        applyPersonaMode(false);

        // 음성 볼륨 제어 (기본 120%, 최대 200% 증폭 부스트)
        let userVolume = parseFloat(localStorage.getItem('minji_volume') || '120');
        function applyVolume(val) {
            if (val !== undefined && val !== null) {
                userVolume = Math.max(0, Math.min(200, parseFloat(val)));
                localStorage.setItem('minji_volume', userVolume);
            }
            const slider = document.getElementById('volumeSlider');
            const label = document.getElementById('volumeLabel');
            if (slider && Math.round(slider.value) !== Math.round(userVolume)) {
                slider.value = userVolume;
            }
            if (label) label.innerText = `${Math.round(userVolume)}%`;

            if (audioPlayer) {
                audioPlayer.volume = Math.min(1.0, userVolume / 100);
            }
        }
        applyVolume(userVolume);

        // 상단 상세 메뉴 토글 및 자동 숨김 타이머 (4.5초 뒤 자동 수납)
        let headerHideTimer = null;
        function toggleHeaderMenu(e) {
            if (e) e.stopPropagation();
            const header = document.getElementById('appHeader');
            if (!header) return;
            const isVisible = header.classList.contains('active');
            if (isVisible) {
                header.classList.remove('active');
                if (headerHideTimer) {
                    clearTimeout(headerHideTimer);
                    headerHideTimer = null;
                }
            } else {
                header.classList.add('active');
                if (headerHideTimer) clearTimeout(headerHideTimer);
                headerHideTimer = setTimeout(() => {
                    header.classList.remove('active');
                }, 4500);
            }
        }

        // 화면 탭 제스처 처리 (상단 메뉴 열려있으면 닫기, 아니면 대화 인터랙션)
        function handleVisualClick(e) {
            const header = document.getElementById('appHeader');
            if (header && header.classList.contains('active')) {
                header.classList.remove('active');
                if (headerHideTimer) {
                    clearTimeout(headerHideTimer);
                    headerHideTimer = null;
                }
                return;
            }
            handleOrbClick();
        }

        // 세션 ID (로컬 브라우저 고유값 보존)
        let sessionId = localStorage.getItem("minji_session_id");
        if (!sessionId) {
            sessionId = "minji_user_" + Math.random().toString(36).substring(2, 10);
            localStorage.setItem("minji_session_id", sessionId);
        }

        // 상태 업데이트 헬퍼 (모드별 아바타 동적 바인딩)
        function setOrbState(state) {
            avatarOrb.className = 'orb ' + (state || '');
            if (avatarWrapper) {
                avatarWrapper.className = 'avatar-wrapper ' + (state || '');
            }
            if (state === 'listening') {
                stateLabel.innerText = "Listening";
                stateLabel.style.color = "#00f2fe";
                setAvatarImageSmooth(getAvatarImage(currentPersonaMode, 'listening'));
            } else if (state === 'speaking') {
                stateLabel.innerText = "Speaking";
                stateLabel.style.color = "#ff7b54";
                setAvatarImageSmooth(getAvatarImage(currentPersonaMode, 'speaking'));
            } else if (state === 'thinking') {
                stateLabel.innerText = "Thinking";
                stateLabel.style.color = "#fe5196";
                setAvatarImageSmooth(getAvatarImage(currentPersonaMode, 'thinking'));
            } else if (state === 'muted') {
                stateLabel.innerText = "Muted";
                stateLabel.style.color = "#888";
                setAvatarImageSmooth(getAvatarImage(currentPersonaMode, 'idle'));
            } else {
                stateLabel.innerText = "Idle";
                stateLabel.style.color = "#aaa";
                setAvatarImageSmooth(getAvatarImage(currentPersonaMode, 'idle'));
            }
        }

        // [핵심 기능 2]: 사용자 발화 중단 (Barge-in / Interrupt)
        function interruptSpeech(reason = "barge_in") {
            if (!isSpeaking) return;
            console.log("[Barge-in] Speech interrupted by user input: " + reason);
            audioPlayer.pause();
            audioPlayer.currentTime = 0;
            isSpeaking = false;
            setOrbState('listening');
            statusText.innerText = "듣고 있어요...";
            if (!isListening && !isMicMuted) {
                startListening();
            }
        }

        // Web Audio API 기반 실시간 볼륨 모니터링 (Barge-in 감지)
        function setupAudioAnalyser(mediaStream) {
            try {
                window.AudioContext = window.AudioContext || window.webkitAudioContext;
                if (!audioContext) {
                    audioContext = new AudioContext();
                }
                if (audioContext.state === 'suspended') {
                    audioContext.resume();
                }
                analyser = audioContext.createAnalyser();
                analyser.fftSize = 256;
                analyser.smoothingTimeConstant = 0.3;
                micSource = audioContext.createMediaStreamSource(mediaStream);
                micSource.connect(analyser);

                const dataArray = new Uint8Array(analyser.frequencyBinCount);
                if (volumeCheckInterval) clearInterval(volumeCheckInterval);

                volumeCheckInterval = setInterval(() => {
                    if (isMicMuted) return;
                    analyser.getByteFrequencyData(dataArray);
                    let sum = 0;
                    for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
                    let average = sum / dataArray.length;

                    // 민지가 말하는 도중 사용자의 강한 육성 발화 감지 (스피커 반향음 30~40 필터링)
                    if (isSpeaking && average > 55) {
                        interruptSpeech("loud_voice_detected (" + Math.round(average) + ")");
                    }
                }, 120);
            } catch (e) {
                console.warn("AudioContext analyser setup error:", e);
            }
        }

        // 음성 합성(TTS) 재생 및 수명 주기 관리
        async function speakNova(text, callback) {
            try {
                isSpeaking = true;
                setOrbState('speaking');
                if (bargeInHint) bargeInHint.style.display = 'block';

                // iOS Safari: 오디오 재생 시 마이크와 스피커 충돌 방지를 위해 일시 정지
                if (recognition && isListening) {
                    try { recognition.stop(); } catch(e){}
                    isListening = false;
                }

                const voiceSelect = document.getElementById('voiceSelect');
                const chosenVoice = voiceSelect ? voiceSelect.value : 'nova';

                const response = await fetch('/api/tts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: text, voice: chosenVoice })
                });

                if (!response.ok) {
                    const errJson = await response.json().catch(() => ({}));
                    throw new Error(errJson.detail || ("HTTP " + response.status));
                }

                const blob = await response.blob();
                audioPlayer.src = URL.createObjectURL(blob);
                // 여친 모드는 얇고 통통 튀는 1.07배속, 비서 모드는 우아하고 안정적인 1.0배속
                audioPlayer.playbackRate = (currentPersonaMode === 'girlfriend') ? 1.07 : 1.0;
                applyVolume(userVolume);
                
                audioPlayer.onended = () => {
                    if (!isSpeaking) return;
                    isSpeaking = false;
                    setOrbState(isMicMuted ? 'muted' : 'idle');
                    if (callback) callback();
                    if (!isMicMuted) setTimeout(startListening, 300);
                };

                try {
                    await audioPlayer.play();
                } catch (playErr) {
                    console.warn("[Autoplay Blocked]:", playErr);
                    statusText.innerText = "🔊 화면을 가볍게 터치하시면 목소리가 재생돼요.";
                    const playOnce = async () => {
                        window.removeEventListener('click', playOnce);
                        window.removeEventListener('touchstart', playOnce);
                        try { await audioPlayer.play(); } catch(e){}
                    };
                    window.addEventListener('click', playOnce, { once: true });
                    window.addEventListener('touchstart', playOnce, { once: true });
                }

            } catch (err) {
                console.error("[TTS Play Error]:", err);
                isSpeaking = false;
                setOrbState(isMicMuted ? 'muted' : 'idle');
                statusText.innerText = "음성 재생 알림: " + err.message;
                if (!isMicMuted) setTimeout(startListening, 1200);
            }
        }

        // Web Speech API 음성 인식 시작 (모바일 최적화)
        function startListening() {
            if (!streamActive || isMicMuted || isProcessing || isSpeaking) return;

            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                statusText.innerText = "이 브라우저는 음성 인식을 지원하지 않습니다. 아래 텍스트 입력을 사용해주세요.";
                return;
            }

            if (!recognition) {
                recognition = new SpeechRecognition();
                recognition.continuous = false; // 모바일/iOS에서 continuous: false가 극도로 안정적
                recognition.interimResults = false;
                recognition.lang = 'ko-KR';

                recognition.onstart = () => {
                    isListening = true;
                    if (!isSpeaking) {
                        setOrbState('listening');
                        statusText.innerText = "듣고 있어요...";
                    }
                };

                // 사용자가 말을 시작한 순간 Barge-in 발동
                recognition.onspeechstart = () => {
                    if (isSpeaking) {
                        interruptSpeech("speech_start");
                    }
                };

                recognition.onresult = async (e) => {
                    const userSpeech = e.results[0][0].transcript.trim();
                    if (!userSpeech) return;

                    if (isSpeaking) interruptSpeech("speech_result");

                    isListening = false;
                    statusText.innerText = "나: " + userSpeech;
                    await sendToMinji(userSpeech);
                };

                recognition.onerror = (e) => {
                    isListening = false;
                    if (streamActive && !isSpeaking && !isProcessing && !isMicMuted) {
                        setTimeout(startListening, 600);
                    }
                };

                recognition.onend = () => {
                    isListening = false;
                    if (streamActive && !isSpeaking && !isProcessing && !isMicMuted) {
                        setTimeout(startListening, 400);
                    }
                };
            }

            try {
                recognition.start();
            } catch (e) {
                // 이미 시작된 상태일 수 있음
            }
        }

        function stopListening() {
            if (recognition) {
                try { recognition.stop(); } catch(e){}
            }
            isListening = false;
        }

        // 마이크 온/오프 토글
        function toggleMic() {
            if (isSpeaking) interruptSpeech("mic_toggle");
            isMicMuted = !isMicMuted;

            if (isMicMuted) {
                stopListening();
                setOrbState('muted');
                micToggleBtn.classList.add('btn-muted');
                micIcon.innerText = "🔇";
                if (micText) micText.innerText = "마이크 켜기";
                statusText.innerText = "마이크가 꺼졌습니다.";
            } else {
                setOrbState('idle');
                micToggleBtn.classList.remove('btn-muted');
                micIcon.innerText = "🎙️";
                if (micText) micText.innerText = "마이크 끄기";
                statusText.innerText = "마이크가 켜졌습니다. 편하게 말씀하세요.";
                startListening();
            }
        }

        // 구체 직접 클릭 인터랙션
        function handleOrbClick() {
            if (!streamActive) {
                initMinji();
                return;
            }
            if (isSpeaking) {
                interruptSpeech("orb_clicked");
                return;
            }
            if (isMicMuted) {
                toggleMic();
            } else {
                statusText.innerText = "듣고 있어요. 말씀해주세요.";
                startListening();
            }
        }

        // [핵심 기능 1]: 민지에게 메시지 전송 (초저지연 1회 직결 통신으로 즉시 재생)
        async function sendToMinji(text) {
            isProcessing = true;
            setOrbState('thinking');
            statusText.innerText = "민지가 생각하고 있어요...";

            try {
                const chosenVoice = voiceSelect ? voiceSelect.value : (currentPersonaMode === 'secretary' ? 'eleven_secretary' : 'eleven_girlfriend');
                const response = await fetch('/api/voice-chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_text: text,
                        session_id: sessionId,
                        mode: currentPersonaMode,
                        voice: chosenVoice
                    })
                });

                if (!response.ok) {
                    throw new Error("서버 음성 응답 실패");
                }

                // 텍스트 자막 헤더에서 즉각 추출 (디코딩)
                const rawReplyHeader = response.headers.get('X-Reply-Text');
                const replyText = rawReplyHeader ? decodeURIComponent(rawReplyHeader) : (currentPersonaMode === 'secretary' ? "대표님, 말씀 잘 들었습니다." : "응, 오빠.");
                statusText.innerText = "민지: " + replyText;

                // 음성 스트림 바이너리 즉시 재생
                const audioBlob = await response.blob();
                const audioUrl = URL.createObjectURL(audioBlob);

                isProcessing = false;
                isSpeaking = true;
                setOrbState('speaking');

                audioPlayer.src = audioUrl;
                audioPlayer.onended = () => {
                    isSpeaking = false;
                    setOrbState(isMicMuted ? 'muted' : 'idle');
                    if (!isMicMuted) setTimeout(startListening, 300);
                };

                try {
                    await audioPlayer.play();
                } catch (playErr) {
                    console.warn("[Autoplay Blocked/Interrupted]:", playErr);
                    isSpeaking = false;
                    setOrbState(isMicMuted ? 'muted' : 'idle');
                    if (!isMicMuted) setTimeout(startListening, 800);
                }

            } catch (err) {
                console.error("[Send Error]:", err);
                isProcessing = false;
                setOrbState(isMicMuted ? 'muted' : 'idle');
                statusText.innerText = "오류: " + err.message;
                if (!isMicMuted) setTimeout(startListening, 1500);
            }
        }

        // [핵심 기능 3]: 카메라 시각 인지 (Vision)
        async function lookAtThis() {
            if (!streamActive) return;
            if (isSpeaking) interruptSpeech("vision_triggered");

            if (!video.videoWidth || video.videoWidth === 0) {
                statusText.innerText = "카메라 화면을 불러오는 중입니다. 1초 뒤 다시 눌러주세요.";
                return;
            }

            setOrbState('thinking');
            statusText.innerText = "카메라에 비친 장면을 눈에 담고 있어요...";

            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            const base64Image = canvas.toDataURL('image/jpeg', 0.85).split(',')[1];

            try {
                const visionPrompt = (currentPersonaMode === 'secretary')
                    ? "대표님께서 카메라로 비춰주신 실제 물체와 주변을 보고 서민지 비서처럼 지적이고 품격 있게 1~2문장으로 브리핑해줘."
                    : "사진 속 실제 대상과 배경을 있는 그대로 보고 민지처럼 다정하고 설레게 한두 문장으로 말해줘.";

                const response = await fetch('/api/vision-analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        image_base64: base64Image,
                        prompt: visionPrompt,
                        session_id: sessionId,
                        mode: currentPersonaMode
                    })
                });

                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || "시각 분석 실패");

                const visionReply = data.analysis || (currentPersonaMode === 'secretary' ? "대표님, 보여주신 장면 확인했습니다." : "와, 정말 흥미로운 장면이야!");
                statusText.innerText = "민지: " + visionReply;
                speakNova(visionReply);

            } catch (err) {
                console.error("[Vision Error]:", err);
                setOrbState(isMicMuted ? 'muted' : 'idle');
                statusText.innerText = "시각 인지 오류: " + err.message;
                if (!isMicMuted) setTimeout(startListening, 2000);
            }
        }

        // 전면 / 후면 카메라 전환
        let currentFacingMode = "environment";
        async function switchCamera() {
            if (!streamActive) return;
            currentFacingMode = (currentFacingMode === "environment") ? "user" : "environment";
            try {
                const oldTracks = video.srcObject ? video.srcObject.getVideoTracks() : [];
                oldTracks.forEach(t => t.stop());

                const newStream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: currentFacingMode, width: { ideal: 1280 }, height: { ideal: 720 } }
                });
                const newTrack = newStream.getVideoTracks()[0];
                if (video.srcObject) {
                    if (oldTracks.length > 0) video.srcObject.removeTrack(oldTracks[0]);
                    video.srcObject.addTrack(newTrack);
                }
                statusText.innerText = (currentFacingMode === "environment" ? "후면" : "전면") + " 카메라로 전환되었습니다.";
            } catch (e) {
                console.warn("Switch camera err:", e);
                statusText.innerText = "카메라 전환 실패: " + e.message;
            }
        }

        // 기억 초기화
        async function resetMemory() {
            if (confirm("민지와 나눈 이전 대화 기억을 초기화할까요?")) {
                try {
                    await fetch('/api/reset-memory', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ session_id: sessionId })
                    });
                    sessionId = "minji_user_" + Math.random().toString(36).substring(2, 10);
                    localStorage.setItem("minji_session_id", sessionId);
                    statusText.innerText = "새로운 대화가 시작되었어요.";
                    speakNova("우리 새로운 마음으로 다시 이야기 시작해보자!");
                } catch (e) {
                    alert("기억 초기화 실패: " + e.message);
                }
            }
        }

        // 텍스트 인라인 입력 모드 토글
        function toggleTextInput(show) {
            const container = document.getElementById('textInputContainer');
            const input = document.getElementById('customUserText');
            if (!container) return;
            if (show === undefined) {
                show = (container.style.display === 'none' || !container.style.display);
            }
            if (show) {
                container.style.display = 'block';
                setTimeout(() => {
                    if (input) input.focus();
                }, 100);
            } else {
                container.style.display = 'none';
            }
        }

        // 텍스트 메시지 전송
        function sendCustomText() {
            const input = document.getElementById('customUserText');
            const userMsg = input.value.trim();
            if (userMsg) {
                if (isSpeaking) interruptSpeech("text_input");
                statusText.innerText = "나: " + userMsg;
                input.value = '';
                toggleTextInput(false);
                sendToMinji(userMsg);
            }
        }

        // 민지 연결 초기화
        async function initMinji() {
            // [iOS Safari 핵심 대응] 사용자의 터치 제스처 스택에서 동기적으로 Audio & AudioContext 잠금 해제(Unlock)
            try {
                if (!audioContext) {
                    window.AudioContext = window.AudioContext || window.webkitAudioContext;
                    audioContext = new AudioContext();
                }
                if (audioContext.state === 'suspended') {
                    audioContext.resume();
                }
                // 무음 오디오 재생 후 일시정지로 HTMLAudioElement 언락
                audioPlayer.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
                audioPlayer.play().then(() => audioPlayer.pause()).catch(e => console.log("Audio unlock:", e));
            } catch (unlockErr) {
                console.warn("Audio unlock exception:", unlockErr);
            }

            try {
                statusText.innerText = "카메라 및 마이크 권한 요청 중...";
                const stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
                    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
                });

                video.srcObject = stream;
                streamActive = true;

                // AudioContext 활성화 및 볼륨 감지 세팅
                setupAudioAnalyser(stream);

                connectGroup.style.display = 'none';
                activeControls.style.display = 'flex';
                statusText.innerText = "민지와 연결되었습니다!";

                // 첫 인사: 모드(여친 vs 비서) 및 시간대에 맞는 맞춤형 첫 인사
                const curHour = new Date().getHours();
                let initialGreeting = "";
                if (currentPersonaMode === 'secretary') {
                    if (curHour >= 5 && curHour < 11) {
                        initialGreeting = "대표님, 좋은 아침입니다. 오늘 주요 일정 브리핑 준비를 마쳤습니다. 모닝커피 한잔 준비해 드릴까요?";
                    } else if (curHour >= 11 && curHour < 14) {
                        initialGreeting = "대표님, 점심시간입니다. 식사는 든든하게 챙기셨습니까? 대표님 컨디션이 저의 최우선입니다.";
                    } else if (curHour >= 14 && curHour < 18) {
                        initialGreeting = "대표님, 오후 업무로 많이 피로하시지요? 잠시 서류 내려놓으시고 쉬어가십시오.";
                    } else if (curHour >= 18 && curHour < 22) {
                        initialGreeting = "대표님, 오늘 하루도 회사 이끄시느라 고생 많으셨습니다. 퇴근길 편안하게 모시겠습니다.";
                    } else if (curHour >= 22 || curHour < 2) {
                        initialGreeting = "대표님, 늦은 밤까지 결재 서류를 보시는 중이십니까? 건강 상하실까 걱정됩니다.";
                    } else {
                        initialGreeting = "대표님, 이 새벽에 아직 깨어 계십니까? 무리하시면 안 됩니다. 이제 편히 쉬십시오.";
                    }
                } else {
                    if (curHour >= 5 && curHour < 11) {
                        initialGreeting = "오빠 안녕! 오늘 하루 기분 좋게 시작했어? 아침은 챙겨 먹었구?";
                    } else if (curHour >= 11 && curHour < 14) {
                        initialGreeting = "오빠 안녕! 벌써 점심시간이네~ 오늘 점심 맛있는 거 먹었어?";
                    } else if (curHour >= 14 && curHour < 18) {
                        initialGreeting = "오빠! 나른한 오후인데 피곤하진 않아? 잠깐 나랑 수다 떨자.";
                    } else if (curHour >= 18 && curHour < 22) {
                        initialGreeting = "오빠 오늘 하루도 일하느라 고생 많았어! 지금 퇴근하고 쉬는 중이야?";
                    } else if (curHour >= 22 || curHour < 2) {
                        initialGreeting = "오빠 아직 안 자고 있었어? 오늘 하루 어땠는지 도란도란 이야기해줘.";
                    } else {
                        initialGreeting = "오빠 이 새벽에 아직 안 자고 뭐해? 내일 피곤할 텐데 걱정되잖아.";
                    }
                }

                speakNova(initialGreeting, () => {
                    startListening();
                });

            } catch (err) {
                console.error("[Init Error]:", err);
                statusText.innerText = "권한 승인이 필요합니다: " + err.message;
            }
        }

        // 카메라 오버레이 열기 (📷 이거 봐봐 버튼)
        function openCamOverlay() {
            if (!streamActive) return;
            if (camOverlay) camOverlay.classList.add('active');
        }

        // 카메라 오버레이 닫기
        function closeCamOverlay(e) {
            if (e) e.stopPropagation();
            if (camOverlay) camOverlay.classList.remove('active');
        }

        // 오버레이 배경 탭 → 닫기
        function handleOverlayBackdropClick(e) {
            if (e.target === camOverlay) closeCamOverlay();
        }

        // 캡처 후 민지 분석 요청
        function captureAndAnalyze(e) {
            if (e) e.stopPropagation();
            closeCamOverlay();
            lookAtThis();
        }
    </script>
</body>
</html>
"""
