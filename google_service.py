"""
Google Calendar & Google Tasks Integration Service for Minji AI
Handles OAuth 2.0 authentication, token management, and bi-directional sync
with Google Calendar API (v3) and Google Tasks API (v1).
"""

import os
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import urllib.parse
import urllib.request
import requests

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
GOOGLE_CONFIG_FILE = os.path.join(CONFIG_DIR, "google_oauth_config.json")
GOOGLE_TOKEN_FILE = os.path.join(CONFIG_DIR, "google_user_token.json")
TASKS_FILE = os.path.join(CONFIG_DIR, "calendar_tasks.json")

# Default Scopes for Calendar & Tasks
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid"
]

def load_json_file(file_path: str, default: Any = None) -> Any:
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[GoogleService] Error reading {file_path}: {e}")
    return default if default is not None else {}

def save_json_file(file_path: str, data: Any):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[GoogleService] Error writing {file_path}: {e}")

def get_oauth_config() -> Dict[str, Any]:
    cfg = load_json_file(GOOGLE_CONFIG_FILE, {})
    # Fallback to environment variables if present
    client_id = cfg.get("client_id") or os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = cfg.get("client_secret") or os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = cfg.get("redirect_uri") or os.getenv("GOOGLE_REDIRECT_URI", "")
    return {
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "redirect_uri": redirect_uri.strip()
    }

def save_oauth_config(client_id: str, client_secret: str, redirect_uri: str = ""):
    cfg = get_oauth_config()
    cfg["client_id"] = client_id.strip()
    cfg["client_secret"] = client_secret.strip()
    if redirect_uri:
        cfg["redirect_uri"] = redirect_uri.strip()
    save_json_file(GOOGLE_CONFIG_FILE, cfg)
    return cfg

def get_tokens() -> Dict[str, Any]:
    return load_json_file(GOOGLE_TOKEN_FILE, {})

def save_tokens(token_data: Dict[str, Any]):
    current = get_tokens()
    current.update(token_data)
    save_json_file(GOOGLE_TOKEN_FILE, current)

def clear_tokens():
    if os.path.exists(GOOGLE_TOKEN_FILE):
        try:
            os.remove(GOOGLE_TOKEN_FILE)
        except Exception as e:
            print(f"[GoogleService] Error removing token file: {e}")

def is_configured() -> bool:
    cfg = get_oauth_config()
    return bool(cfg.get("client_id") and cfg.get("client_secret"))

def is_connected() -> bool:
    tokens = get_tokens()
    return bool(tokens.get("refresh_token") or tokens.get("access_token"))

def generate_auth_url(redirect_uri: str) -> str:
    cfg = get_oauth_config()
    client_id = cfg.get("client_id")
    if not client_id:
        raise ValueError("Google Client ID가 설정되지 않았습니다.")
    
    # Save the used redirect_uri
    cfg["redirect_uri"] = redirect_uri
    save_json_file(GOOGLE_CONFIG_FILE, cfg)
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true"
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

def exchange_code_for_tokens(code: str, redirect_uri: str) -> Dict[str, Any]:
    cfg = get_oauth_config()
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError("Google Client ID / Secret이 누락되었습니다.")
    
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    res = requests.post(token_url, data=payload, timeout=10)
    if res.status_code != 200:
        raise RuntimeError(f"Google Token 발급 실패: {res.text}")
    
    token_data = res.json()
    now_ts = int(time.time())
    expires_in = token_data.get("expires_in", 3600)
    token_data["token_expiry_ts"] = now_ts + expires_in
    
    # Get user email
    user_email = ""
    access_token = token_data.get("access_token")
    if access_token:
        try:
            info_res = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=5
            )
            if info_res.status_code == 200:
                user_email = info_res.json().get("email", "")
        except Exception as e:
            print(f"[GoogleService] Userinfo fetch error: {e}")
            
    token_data["user_email"] = user_email
    token_data["connected_at"] = datetime.now().isoformat()
    save_tokens(token_data)
    
    # Trigger first sync
    sync_google_data()
    return token_data

def refresh_access_token_if_needed() -> Optional[str]:
    tokens = get_tokens()
    if not tokens:
        return None
    
    access_token = tokens.get("access_token")
    expiry_ts = tokens.get("token_expiry_ts", 0)
    now_ts = int(time.time())
    
    # If valid for at least 3 minutes, return existing access_token
    if access_token and (expiry_ts - now_ts) > 180:
        return access_token
    
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return access_token
    
    cfg = get_oauth_config()
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    if not client_id or not client_secret:
        return access_token
    
    try:
        res = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            },
            timeout=10
        )
        if res.status_code == 200:
            new_data = res.json()
            access_token = new_data.get("access_token")
            expires_in = new_data.get("expires_in", 3600)
            tokens["access_token"] = access_token
            tokens["token_expiry_ts"] = int(time.time()) + expires_in
            save_tokens(tokens)
            return access_token
        else:
            print(f"[GoogleService] Token refresh failed: {res.text}")
    except Exception as e:
        print(f"[GoogleService] Refresh request error: {e}")
    
    return access_token

def fetch_google_calendar_events(days_ahead: int = 7) -> List[Dict[str, Any]]:
    access_token = refresh_access_token_if_needed()
    if not access_token:
        return []
    
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    # Start from beginning of today
    time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    time_max = (now + timedelta(days=days_ahead)).replace(hour=23, minute=59, second=59).isoformat()
    
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 30
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code != 200:
            print(f"[GoogleService] Calendar fetch error {res.status_code}: {res.text}")
            return []
        
        items = res.json().get("items", [])
        events = []
        for item in items:
            summary = item.get("summary", "일정")
            start = item.get("start", {})
            start_date_time = start.get("dateTime") or start.get("date", "")
            
            # Format time & date
            date_str = ""
            time_str = "종일"
            if "T" in start_date_time:
                try:
                    dt = datetime.fromisoformat(start_date_time.replace("Z", "+00:00")).astimezone(kst)
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")
                except Exception:
                    date_str = start_date_time[:10]
            else:
                date_str = start_date_time[:10]
            
            events.append({
                "id": item.get("id", f"gcal_{int(time.time())}"),
                "title": summary,
                "date": date_str,
                "time": time_str,
                "note": item.get("description", "") or item.get("location", ""),
                "html_link": item.get("htmlLink", ""),
                "is_google": True
            })
        return events
    except Exception as e:
        print(f"[GoogleService] Calendar fetch exception: {e}")
        return []

def fetch_google_tasks() -> List[Dict[str, Any]]:
    access_token = refresh_access_token_if_needed()
    if not access_token:
        return []
    
    url = "https://tasks.googleapis.com/tasks/v1/lists/@default/tasks"
    params = {
        "showCompleted": "false",
        "showHidden": "false",
        "maxResults": 30
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code != 200:
            print(f"[GoogleService] Tasks fetch error {res.status_code}: {res.text}")
            return []
        
        items = res.json().get("items", [])
        tasks = []
        for item in items:
            title = item.get("title", "").strip()
            if not title:
                continue
            
            due = item.get("due", "")
            due_date = due[:10] if due else ""
            tasks.append({
                "id": item.get("id", f"gtask_{int(time.time())}"),
                "title": title,
                "due_date": due_date,
                "note": item.get("notes", ""),
                "completed": item.get("status") == "completed",
                "is_google": True
            })
        return tasks
    except Exception as e:
        print(f"[GoogleService] Tasks fetch exception: {e}")
        return []

def add_google_calendar_event(title: str, start_dt: datetime, end_dt: Optional[datetime] = None, note: str = "") -> Optional[Dict[str, Any]]:
    access_token = refresh_access_token_if_needed()
    if not access_token:
        return None
    
    if end_dt is None:
        end_dt = start_dt + timedelta(hours=1)
    
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    body = {
        "summary": title,
        "description": note,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()}
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        res = requests.post(url, json=body, headers=headers, timeout=10)
        if res.status_code in (200, 201):
            sync_google_data()
            return res.json()
        print(f"[GoogleService] Add event error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[GoogleService] Add event exception: {e}")
    return None

def add_google_task(title: str, due_date: Optional[str] = None, note: str = "") -> Optional[Dict[str, Any]]:
    access_token = refresh_access_token_if_needed()
    if not access_token:
        return None
    
    url = "https://tasks.googleapis.com/tasks/v1/lists/@default/tasks"
    body: Dict[str, Any] = {"title": title}
    if note:
        body["notes"] = note
    if due_date:
        # RFC 3339 format required by Google Tasks
        body["due"] = f"{due_date}T00:00:00.000Z"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        res = requests.post(url, json=body, headers=headers, timeout=10)
        if res.status_code in (200, 201):
            sync_google_data()
            return res.json()
        print(f"[GoogleService] Add task error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[GoogleService] Add task exception: {e}")
    return None

def complete_google_task(task_id: str) -> bool:
    access_token = refresh_access_token_if_needed()
    if not access_token:
        return False
    
    url = f"https://tasks.googleapis.com/tasks/v1/lists/@default/tasks/{task_id}"
    body = {"status": "completed"}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        res = requests.patch(url, json=body, headers=headers, timeout=10)
        if res.status_code == 200:
            sync_google_data()
            return True
    except Exception as e:
        print(f"[GoogleService] Complete task exception: {e}")
    return False

def sync_google_data() -> Dict[str, Any]:
    """
    Syncs Google Calendar & Google Tasks into calendar_tasks.json
    and merges with existing manual items.
    """
    if not is_connected():
        return load_json_file(TASKS_FILE, {"events": [], "tasks": []})
    
    tokens = get_tokens()
    user_email = tokens.get("user_email", "")
    
    g_events = fetch_google_calendar_events(days_ahead=7)
    g_tasks = fetch_google_tasks()
    
    existing = load_json_file(TASKS_FILE, {"events": [], "tasks": []})
    manual_events = [e for e in existing.get("events", []) if not e.get("is_google")]
    manual_tasks = [t for t in existing.get("tasks", []) if not t.get("is_google")]
    
    combined_events = g_events + manual_events
    combined_tasks = g_tasks + manual_tasks
    
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    
    updated_data = {
        "last_synced": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
        "user_email": user_email,
        "is_google_connected": True,
        "events": combined_events,
        "tasks": combined_tasks
    }
    save_json_file(TASKS_FILE, updated_data)
    print(f"[GoogleService] Synced: {len(g_events)} events, {len(g_tasks)} tasks for {user_email}")
    return updated_data

def get_google_status() -> Dict[str, Any]:
    cfg = get_oauth_config()
    tokens = get_tokens()
    current_data = load_json_file(TASKS_FILE, {"events": [], "tasks": []})
    
    kst = timezone(timedelta(hours=9))
    today_str = datetime.now(kst).strftime("%Y-%m-%d")
    
    today_events = [e for e in current_data.get("events", []) if e.get("date") == today_str]
    pending_tasks = [t for t in current_data.get("tasks", []) if not t.get("completed")]
    
    return {
        "is_configured": bool(cfg.get("client_id") and cfg.get("client_secret")),
        "is_connected": is_connected(),
        "client_id_preview": (cfg.get("client_id", "")[:12] + "...") if cfg.get("client_id") else "",
        "user_email": tokens.get("user_email", ""),
        "last_synced": current_data.get("last_synced", "동기화 이력 없음"),
        "today_event_count": len(today_events),
        "pending_task_count": len(pending_tasks),
        "events": current_data.get("events", []),
        "tasks": current_data.get("tasks", [])
    }
