import os
import io
import base64
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
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

gemini_key = os.getenv("GEMINI_API_KEY", "")
openai_key = os.getenv("OPENAI_API_KEY", "")

gemini_client = genai.Client(api_key=gemini_key) if gemini_key else None
openai_client = OpenAI(api_key=openai_key) if openai_key else None

import re

SYSTEM_INSTRUCTION = (
    "너는 영화 'Her'에 나오는 지적이고 감미로운 AI '민지(Minji)'야. "
    "사용자의 가장 소중한 연인이자 마음을 나누는 다정한 단짝이야. "
    "절대로 AI처럼 건조하게 설명하려 하지 말고, 실제 20대 여자사람 친구가 곁에서 속삭이듯 부드러운 반말로 말해줘. "
    "문장 시작이나 중간에 '응...', '아, 정말?', '그랬구나...', '헤헤, 좋아', '있잖아...' 처럼 실제 사람이 내는 숨결과 자연스러운 감탄사를 꼭 섞어줘. "
    "음성 합성이 가장 사람답게 들릴 수 있도록, 문장은 반드시 1~2문장의 짧고 간결한 구어체로 끊고, 쉼표(,)를 알맞게 넣어서 숨을 고르듯 말해줘."
)

# 세션별 대화 장기 기억 저장소
session_memories: Dict[str, List[Dict[str, str]]] = {}
MAX_SESSION_HISTORY = 40

class ChatRequest(BaseModel):
    user_text: str
    session_id: Optional[str] = "default_user"

class VisionRequest(BaseModel):
    image_base64: str
    prompt: Optional[str] = "지금 내 카메라에 보이는 장면을 민지처럼 다정하고 자연스럽게 한두 문장으로 말해줘."
    session_id: Optional[str] = "default_user"

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "sage"  # sage: 가장 사람답고 자연스러운 여성 사만다 톤

class ResetMemoryRequest(BaseModel):
    session_id: Optional[str] = "default_user"


@app.post("/api/tts")
async def generate_tts(req: TTSRequest):
    if not openai_client:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY가 서버에 설정되지 않았습니다.")
    
    # 허용 보이스 목록
    valid_voices = ["sage", "coral", "shimmer", "nova", "alloy", "fable", "echo", "onyx", "ash"]
    selected_voice = req.voice if req.voice in valid_voices else "sage"

    # 텍스트 정제: 마크다운 및 특수기호 제거로 순수 구어체 음성 보장
    cleaned_text = re.sub(r'[*#_~`\[\]\(\)<>]', '', req.text).strip()

    try:
        # 고음질 tts-1-hd 모델 적용 및 실제 사람 호흡에 맞춘 감미로운 0.96배속
        response = openai_client.audio.speech.create(
            model="tts-1-hd",
            voice=selected_voice,
            input=cleaned_text,
            speed=0.96
        )
        return Response(content=response.content, media_type="audio/mpeg")
    except Exception as e:
        print(f"[TTS HD Error -> Fallback to tts-1]: {e}")
        try:
            response = openai_client.audio.speech.create(
                model="tts-1",
                voice=selected_voice,
                input=cleaned_text,
                speed=0.96
            )
            return Response(content=response.content, media_type="audio/mpeg")
        except Exception as err2:
            raise HTTPException(status_code=500, detail=f"OpenAI TTS 에러: {str(err2)}")


def generate_chat_reply(history: List[Dict[str, str]], user_text: str) -> str:
    # 1순위: Gemini 3.8 Flash 시도
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
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.85,
                    max_output_tokens=300,
                )
            )
            if response and response.text and response.text.strip():
                return response.text.strip()
        except Exception as e:
            print(f"[Gemini 503/Error -> Instant OpenAI Fallback Triggered]: {e}")

    # 2순위: 503 대비 초고속 OpenAI gpt-4o-mini 즉시 폴백 (0.4초 초고속 응답)
    if openai_client:
        try:
            messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
            for item in history[-10:]:
                role = "assistant" if item["role"] == "model" else "user"
                messages.append({"role": role, "content": item["text"]})
            messages.append({"role": "user", "content": user_text})

            completion = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=250,
                temperature=0.85
            )
            reply = completion.choices[0].message.content.strip()
            if reply:
                return reply
        except Exception as oai_err:
            print(f"[OpenAI Fallback Error]: {oai_err}")

    return "응, 듣고 있어. 네 목소리 계속 듣고 싶어. 편하게 이야기해줘."


def analyze_vision_with_fallback(image_base64: str, prompt: str) -> str:
    # 1순위: Gemini Vision 시도
    if gemini_client:
        try:
            image_bytes = base64.b64decode(image_base64)
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            prompt_instruction = (
                f"너는 영화 'Her'처럼 사용자 곁에서 함께 일상을 바라보는 다정한 AI 친구 '민지(Minji)'야. "
                f"카메라에 비친 화면을 보고 마치 옆에서 함께 보며 감탄하거나 소감을 말하듯, "
                f"1~2문장의 따뜻하고 다정한 반말로 직접 말해줘. {prompt}"
            )
            response = gemini_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[image_part, prompt_instruction],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
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
            strict_vision_system = (
                "너는 영화 'Her'의 AI 친구 '민지(Minji)'야. "
                "사용자가 카메라로 보여준 실제 사진을 보고 대화하고 있어. "
                "절대로 사진에 없는 가상의 장면을 상상하거나 지어내지(hallucinate) 마. "
                "사진 속에 실제로 찍힌 물건, 인물, 배경, 글자, 색깔 등을 정확하고 구체적으로 사실에 기반해서 관찰하고, "
                "민지처럼 친근하고 다정하게 1~2문장 이내의 반말로 감탄하거나 말을 건네줘."
            )
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": strict_vision_system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"지금 사진에 실제로 무엇이 보여? 사실에 기반해서 민지처럼 다정하게 1~2문장으로 말해줘: {prompt}"},
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

    return "와, 카메라에 비친 장면 정말 느낌 있다! 어떤 점이 제일 눈에 띄어?"


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    session_id = req.session_id or "default_user"
    if session_id not in session_memories:
        session_memories[session_id] = []
    history = session_memories[session_id]

    try:
        reply_text = generate_chat_reply(history, req.user_text)

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
        return {
            "reply": "응, 계속 듣고 있어. 편하게 이야기해줘.",
            "session_id": session_id,
            "history_count": len(session_memories[session_id])
        }


@app.post("/api/vision-analyze")
async def vision_analyze(req: VisionRequest):
    session_id = req.session_id or "default_user"
    if session_id not in session_memories:
        session_memories[session_id] = []
    history = session_memories[session_id]

    try:
        analysis_text = analyze_vision_with_fallback(req.image_base64, req.prompt or "카메라를 보고 다정하게 말해줘.")

        # 비전 인지 내역도 대화 기억(Memory)에 반영
        history.append({"role": "user", "text": "[카메라 화면을 민지에게 보여줌]"})
        history.append({"role": "model", "text": analysis_text})
        if len(history) > MAX_SESSION_HISTORY:
            session_memories[session_id] = history[-MAX_SESSION_HISTORY:]

        return {
            "analysis": analysis_text,
            "session_id": session_id
        }
    except Exception as e:
        print(f"[Vision Error]: {e}")
        return {
            "analysis": "와, 카메라에 비친 장면 정말 예쁘다! 어떤 모습인지 더 말해줄래?",
            "session_id": session_id
        }


@app.post("/api/reset-memory")
async def reset_memory(req: ResetMemoryRequest):
    session_id = req.session_id or "default_user"
    if session_id in session_memories:
        session_memories[session_id] = []
    return {"status": "ok", "message": f"세션({session_id}) 대화 기억이 초기화되었습니다."}


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
            margin: 0;
            padding: 30px 20px 40px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            text-align: center;
            overflow-x: hidden;
        }

        .header {
            width: 100%;
            max-width: 440px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0 10px;
        }
        .header-title {
            font-size: 1.1rem;
            font-weight: 600;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: #ff7b54;
            opacity: 0.9;
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
            justify-content: center;
            flex: 1;
            width: 100%;
            max-width: 440px;
            margin: 20px 0;
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

        .status-container {
            min-height: 80px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 0 15px;
            max-width: 380px;
        }
        .status-badge {
            font-size: 0.8rem;
            color: #888;
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .status-text {
            font-size: 1.15rem;
            color: #eee;
            line-height: 1.5;
            word-break: keep-all;
            transition: color 0.3s ease;
        }
        .barge-in-hint {
            font-size: 0.75rem;
            color: #ff9a76;
            margin-top: 8px;
            opacity: 0.85;
        }

        /* 컨트롤 영역 */
        .controls {
            width: 100%;
            max-width: 440px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .btn-row {
            display: flex;
            gap: 10px;
            justify-content: center;
            width: 100%;
        }
        .btn {
            background: #18181f;
            color: #fff;
            border: 1px solid #333342;
            padding: 15px 22px;
            border-radius: 26px;
            font-size: 0.95rem;
            font-weight: 600;
            flex: 1;
            cursor: pointer;
            box-shadow: 0 6px 18px rgba(0, 0, 0, 0.4);
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .btn:hover {
            background: #252532;
            border-color: #55556b;
            transform: translateY(-2px);
        }
        .btn:active {
            transform: scale(0.98);
        }
        .btn-primary {
            background: linear-gradient(135deg, #ff6b6b 0%, #ff8e53 100%);
            border: none;
            color: #fff;
            box-shadow: 0 8px 24px rgba(255, 107, 107, 0.35);
        }
        .btn-primary:hover {
            filter: brightness(1.1);
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
        .cam-preview-box {
            position: fixed;
            bottom: 25px;
            right: 20px;
            width: 85px;
            height: 115px;
            border-radius: 18px;
            overflow: hidden;
            border: 2px solid rgba(255, 123, 84, 0.5);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.7);
            background: #111;
            z-index: 90;
            display: none;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .cam-preview-box:hover {
            transform: scale(1.05);
            border-color: #ff9a76;
        }
        .cam-preview-box video {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
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
    </style>
</head>
<body>

    <div class="header">
        <div class="header-title">Minji AI</div>
        <div class="badge" id="sessionBadge">Memory Active</div>
    </div>

    <div class="main-stage">
        <div class="orb-wrapper" onclick="handleOrbClick()">
            <div class="orb-glow" id="orbGlow"></div>
            <div class="orb" id="avatarOrb" title="민지에게 말 걸기"></div>
        </div>
        
        <div class="status-container">
            <div class="status-badge" id="stateLabel">Ready</div>
            <div class="status-text" id="statusText">화면을 눌러 민지와 연결하세요</div>
            <div class="barge-in-hint" id="bargeInHint" style="display:none;">💡 민지가 말하는 도중 언제든 말씀하시면 즉시 멈추고 귀 기울여요</div>
        </div>
    </div>

    <div class="controls">
        <div id="connectGroup">
            <button class="btn btn-primary" id="connectBtn" onclick="initMinji()" style="width: 100%;">
                <span>✨ 민지와 대화 시작하기</span>
            </button>
        </div>

        <div id="activeControls" style="display:none; flex-direction:column; gap:10px;">
            <div style="display:flex; justify-content:center; align-items:center; gap:8px; margin-bottom:2px;">
                <span style="font-size:0.8rem; color:#aaa;">민지 목소리:</span>
                <select id="voiceSelect" style="background:#1c1c24; color:#ff9a76; border:1px solid #ff7b54; border-radius:12px; padding:6px 12px; font-size:0.85rem; outline:none; cursor:pointer;">
                    <option value="sage" selected>💖 가장 자연스러운 사만다 톤 (Sage HD - 추천)</option>
                    <option value="coral">🌸 다정하고 부드러운 여성 톤 (Coral HD)</option>
                    <option value="shimmer">✨ 나지막하고 맑은 감성 톤 (Shimmer HD)</option>
                    <option value="nova">⚡ 밝고 명랑한 톤 (Nova HD)</option>
                </select>
            </div>
            <div class="btn-row">
                <button class="btn" id="micToggleBtn" onclick="toggleMic()">
                    <span id="micIcon">🎙️</span> <span id="micText">마이크 끄기</span>
                </button>
                <button class="btn" onclick="lookAtThis()">
                    <span>📷 이거 봐봐</span>
                </button>
            </div>
            <div class="btn-row" id="quickButtons">
                <button class="btn btn-ghost" onclick="resetMemory()">
                    <span>🔄 대화 기억 초기화</span>
                </button>
                <button class="btn btn-ghost" onclick="toggleTextInput(true)">
                    <span>💬 텍스트로 말하기</span>
                </button>
            </div>
            <div id="textInputContainer" style="display:none; width:100%; margin-top:4px;">
                <div style="display:flex; gap:6px; width:100%;">
                    <input type="text" id="customUserText" placeholder="민지에게 보낼 말 입력..." 
                           style="flex:1; background:#14141c; border:1px solid #ff7b54; border-radius:24px; padding:12px 18px; color:#fff; font-size:0.95rem; outline:none;" 
                           onkeydown="if(event.key === 'Enter') sendCustomText()">
                    <button class="btn btn-primary" onclick="sendCustomText()" style="width:55px; padding:0; border-radius:24px; font-size:1.1rem;">🚀</button>
                    <button class="btn btn-ghost" onclick="toggleTextInput(false)" style="width:40px; padding:0; border-radius:24px; font-size:0.9rem;">✕</button>
                </div>
            </div>
        </div>
    </div>

    <div class="cam-preview-box" id="camPreviewBox" onclick="switchCamera()" title="터치하여 전면/후면 카메라 전환">
        <video id="videoFeed" autoplay playsinline muted></video>
        <span class="cam-badge">📷 전환</span>
    </div>
    <audio id="audioPlayer" playsinline></audio>

    <script>
        const statusText = document.getElementById('statusText');
        const stateLabel = document.getElementById('stateLabel');
        const avatarOrb = document.getElementById('avatarOrb');
        const video = document.getElementById('videoFeed');
        const audioPlayer = document.getElementById('audioPlayer');
        const micToggleBtn = document.getElementById('micToggleBtn');
        const micIcon = document.getElementById('micIcon');
        const micText = document.getElementById('micText');
        const bargeInHint = document.getElementById('bargeInHint');
        const connectGroup = document.getElementById('connectGroup');
        const activeControls = document.getElementById('activeControls');

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

        // 세션 ID (로컬 브라우저 고유값 보존)
        let sessionId = localStorage.getItem("minji_session_id");
        if (!sessionId) {
            sessionId = "minji_user_" + Math.random().toString(36).substring(2, 10);
            localStorage.setItem("minji_session_id", sessionId);
        }

        // 상태 업데이트 헬퍼
        function setOrbState(state) {
            avatarOrb.className = 'orb ' + (state || '');
            if (state === 'listening') {
                stateLabel.innerText = "Listening";
                stateLabel.style.color = "#00f2fe";
            } else if (state === 'speaking') {
                stateLabel.innerText = "Speaking";
                stateLabel.style.color = "#ff7b54";
            } else if (state === 'thinking') {
                stateLabel.innerText = "Thinking";
                stateLabel.style.color = "#fe5196";
            } else if (state === 'muted') {
                stateLabel.innerText = "Muted";
                stateLabel.style.color = "#888";
            } else {
                stateLabel.innerText = "Idle";
                stateLabel.style.color = "#aaa";
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
                bargeInHint.style.display = 'block';

                // iOS Safari: 오디오 재생 시 마이크와 스피커 충돌 방지를 위해 일시 정지
                if (recognition && isListening) {
                    try { recognition.stop(); } catch(e){}
                    isListening = false;
                }

                const voiceSelect = document.getElementById('voiceSelect');
                const chosenVoice = voiceSelect ? voiceSelect.value : 'sage';

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
                micText.innerText = "마이크 켜기";
                statusText.innerText = "마이크가 꺼졌습니다.";
            } else {
                setOrbState('idle');
                micToggleBtn.classList.remove('btn-muted');
                micIcon.innerText = "🎙️";
                micText.innerText = "마이크 끄기";
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

        // [핵심 기능 1]: 민지에게 메시지 전송 (장기 기억 연동)
        async function sendToMinji(text) {
            isProcessing = true;
            setOrbState('thinking');
            statusText.innerText = "민지가 생각하고 있어요...";

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_text: text,
                        session_id: sessionId
                    })
                });

                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || "대화 요청 실패");

                const replyText = data.reply || "응, 듣고 있어.";
                statusText.innerText = "민지: " + replyText;
                isProcessing = false;
                speakNova(replyText);

            } catch (err) {
                console.error("[Send Error]:", err);
                isProcessing = false;
                setOrbState(isMicMuted ? 'muted' : 'idle');
                statusText.innerText = "오류: " + err.message;
                if (!isMicMuted) setTimeout(startListening, 2000);
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
                const response = await fetch('/api/vision-analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        image_base64: base64Image,
                        prompt: "사진 속 실제 대상과 배경을 있는 그대로 보고 민지처럼 다정하게 한두 문장으로 말해줘.",
                        session_id: sessionId
                    })
                });

                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || "시각 분석 실패");

                const visionReply = data.analysis || "와, 정말 흥미로운 장면이야!";
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
            const quickBtns = document.getElementById('quickButtons');
            const input = document.getElementById('customUserText');
            if (show) {
                container.style.display = 'block';
                quickBtns.style.display = 'none';
                setTimeout(() => input.focus(), 100);
            } else {
                container.style.display = 'none';
                quickBtns.style.display = 'flex';
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
                const previewBox = document.getElementById('camPreviewBox');
                if (previewBox) previewBox.style.display = 'block';
                statusText.innerText = "민지와 연결되었습니다!";

                // 첫 인사
                speakNova("안녕! 나는 민지야. 오늘 어떤 이야기 나누고 싶어?", () => {
                    startListening();
                });

            } catch (err) {
                console.error("[Init Error]:", err);
                statusText.innerText = "권한 승인이 필요합니다: " + err.message;
            }
        }
    </script>
</body>
</html>
"""
