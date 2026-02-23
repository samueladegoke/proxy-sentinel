"""
Proxy Sentinel API - High Performance Version
==============================================
FastAPI backend with async proxy checking and real-time progress streaming.

PERFORMANCE OPTIMIZATIONS:
1. True async with aiohttp (no thread pool overhead)
2. Large connection pool (100 concurrent connections)
3. Real-time progress streaming via WebSocket
4. Optimized timeout handling (8s default)
5. Streaming results to frontend
"""
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any, Set
import asyncio
import time
import threading
import os
import logging
import json
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Import async proxy library
from proxy_lib_async import (
    check_proxies_stream,
    check_proxies_batch_async,
    check_single_proxy_async,
    cleanup as cleanup_db,
    get_db_stats
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:3000").split(",")
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "100"))  # Increased from 50
DEFAULT_TRACKING_INTERVAL = int(os.getenv("TRACKING_INTERVAL_MINUTES", "5"))
PROXY_FILE = os.getenv("PROXY_FILE", "../proxies.txt")
PROXY_TIMEOUT = int(os.getenv("PROXY_TIMEOUT", "8"))  # Reduced from 12s


# --- Pydantic Models ---

class TrackRequest(BaseModel):
    session: str = Field(..., min_length=1, max_length=100)
    proxy: Optional[str] = Field(None, description="Full proxy string (host:port:user:pass). Required when using custom proxies not in the default list.")
    
    @validator('session')
    def validate_session(cls, v):
        # Allow alphanumeric with dashes and underscores
        cleaned = v.replace('-', '').replace('_', '')
        if not cleaned.isalnum():
            raise ValueError('Session ID contains invalid characters')
        return v


class CheckRequest(BaseModel):
    proxies: Optional[List[str]] = Field(None, max_items=500)
    protocol: str = Field("http")
    
    @validator('protocol')
    def validate_protocol(cls, v):
        valid = ["http", "https", "socks4", "socks5"]
        if v.lower() not in valid:
            raise ValueError(f'Protocol must be one of: {valid}')
        return v.lower()


class TrackingConfigRequest(BaseModel):
    interval_minutes: int = Field(..., ge=1, le=60)


class ProxyResponse(BaseModel):
    session: str
    status: str
    query: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    isp: Optional[str] = None
    mobile: Optional[bool] = None
    hosting: Optional[bool] = None
    proxy: Optional[bool] = None
    local_city: Optional[str] = None
    local_region: Optional[str] = None
    risk_level: Optional[str] = None
    is_valid_carrier: Optional[bool] = None
    error: Optional[str] = None
    error_type: Optional[str] = None


# --- WebSocket Connection Manager ---

class ConnectionManager:
    """Manages WebSocket connections for real-time notifications."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = threading.Lock()
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        with self._lock:
            self.active_connections.add(websocket)
    
    def disconnect(self, websocket: WebSocket):
        with self._lock:
            self.active_connections.discard(websocket)
    
    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        
        message_json = json.dumps(message)
        disconnected = set()
        
        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.add(connection)
        
        if disconnected:
            with self._lock:
                self.active_connections -= disconnected
    
    def count(self) -> int:
        return len(self.active_connections)


# Global instances
ws_manager = ConnectionManager()


# --- Tracking Manager ---

class TrackingManager:
    """Thread-safe manager for tracked proxy sessions."""
    
    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._interval_minutes = DEFAULT_TRACKING_INTERVAL
        self._ip_change_events: List[Dict[str, Any]] = []
    
    def add(self, session_id: str, proxy: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                return False
            self._sessions[session_id] = {
                "proxy": proxy,
                "last_ip": None,
                "last_check": None,
                "history": [],
                "started_at": time.time()
            }
            return True
    
    def remove(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False
    
    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._sessions.get(session_id)
    
    def get_all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._sessions)
    
    def update(self, session_id: str, data: Dict[str, Any]) -> bool:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].update(data)
                return True
            return False
    
    def record_ip_change(self, session_id: str, old_ip: str, new_ip: str, city: str = None):
        event = {
            "type": "ip_change",
            "session": session_id,
            "old_ip": old_ip,
            "new_ip": new_ip,
            "city": city,
            "timestamp": time.time()
        }
        with self._lock:
            self._ip_change_events.append(event)
            if len(self._ip_change_events) > 100:
                self._ip_change_events = self._ip_change_events[-100:]
        return event
    
    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
    
    def set_interval(self, minutes: int):
        with self._lock:
            self._interval_minutes = minutes
    
    def get_interval(self) -> int:
        with self._lock:
            return self._interval_minutes


tracking_manager = TrackingManager()
scheduler = AsyncIOScheduler()


def load_proxies_from_file(filepath: str) -> List[str]:
    """Load proxies from a file."""
    proxies = []
    
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    proxies.append(line)
        logger.info(f"Loaded {len(proxies)} proxies from {filepath}")
    
    return proxies


DEFAULT_PROXIES = load_proxies_from_file(PROXY_FILE)


# --- Application Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    logger.info("Starting Proxy Sentinel API (High Performance Mode)...")
    logger.info(f"CORS Origins: {CORS_ORIGINS}")
    logger.info(f"Max Concurrent: {MAX_CONCURRENT}")
    logger.info(f"Proxy Timeout: {PROXY_TIMEOUT}s")
    logger.info(f"DB Stats: {get_db_stats()}")
    
    scheduler.add_job(
        perform_tracking_checks,
        'interval',
        minutes=tracking_manager.get_interval(),
        id='tracking_check'
    )
    scheduler.start()
    
    yield
    
    logger.info("Shutting down Proxy Sentinel API...")
    scheduler.shutdown(wait=False)
    cleanup_db()
    logger.info("Cleanup complete")


app = FastAPI(
    title="Proxy Sentinel API",
    description="High-Performance Proxy Monitoring with Real-time Progress",
    version="3.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# --- Exception Handlers ---

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"}
    )


# --- API Endpoints ---

@app.get("/")
def read_root():
    return {
        "message": "Proxy Sentinel API (High Performance)",
        "version": "3.0.0",
        "tracked_sessions": tracking_manager.count(),
        "default_proxies": len(DEFAULT_PROXIES),
        "websocket_connections": ws_manager.count(),
        "max_concurrent": MAX_CONCURRENT
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": get_db_stats(),
        "tracked_sessions": tracking_manager.count(),
        "websocket_connections": ws_manager.count(),
        "tracking_interval": tracking_manager.get_interval(),
        "max_concurrent": MAX_CONCURRENT,
        "proxy_timeout": PROXY_TIMEOUT
    }


@app.post("/api/check", response_model=Dict[str, Any])
async def check_proxies_endpoint(request: Optional[CheckRequest] = None):
    """Check proxies and return all results at once."""
    proxies_to_check = DEFAULT_PROXIES
    protocol = "http"
    
    if request:
        if request.proxies:
            proxies_to_check = request.proxies
        protocol = request.protocol
    
    if not proxies_to_check:
        raise HTTPException(status_code=400, detail="No proxies to check")
    
    try:
        results = await check_proxies_batch_async(
            proxies_to_check,
            protocol=protocol,
            max_concurrent=MAX_CONCURRENT,
            timeout=PROXY_TIMEOUT
        )
    except Exception as e:
        logger.error(f"Error checking proxies: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    return {
        "count": len(results),
        "results": results
    }


@app.post("/api/check/single", response_model=ProxyResponse)
async def check_single_endpoint(request: CheckRequest):
    """Check a single proxy."""
    if len(request.proxies) != 1:
        raise HTTPException(status_code=400, detail="Provide exactly one proxy")
    
    # Import the async wrapper
    from proxy_lib_async import check_single_proxy_async_wrapper
    
    result = await check_single_proxy_async_wrapper(
        request.proxies[0],
        protocol=request.protocol,
        timeout=PROXY_TIMEOUT
    )
    return result


@app.post("/api/track")
async def track_proxy(request: TrackRequest, background_tasks: BackgroundTasks):
    """Start tracking a proxy session.
    
    Accepts either:
    1. A session ID that exists in DEFAULT_PROXIES (auto-resolved)
    2. A session ID + full proxy string (for custom proxies from WebSocket check)
    """
    target_proxy = request.proxy  # Use explicitly provided proxy first
    
    if not target_proxy:
        # Fall back to searching default proxies by session ID
        target_proxy = next(
            (p for p in DEFAULT_PROXIES if request.session in p),
            None
        )
    
    if not target_proxy:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Session '{request.session}' not found in default proxy list. "
                "When using custom proxies, provide the full proxy string in the 'proxy' field."
            )
        )
    
    added = tracking_manager.add(request.session, target_proxy)
    
    if not added:
        return {
            "status": "success",
            "message": f"Session '{request.session}' is already being tracked"
        }
    
    # Trigger an immediate check so the user gets instant feedback
    background_tasks.add_task(perform_tracking_checks)

    return {
        "status": "success",
        "message": f"Started tracking session '{request.session}'",
        "interval_minutes": tracking_manager.get_interval()
    }


@app.delete("/api/track/{session_id}")
def stop_tracking(session_id: str):
    """Stop tracking a proxy session."""
    removed = tracking_manager.remove(session_id)
    
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found"
        )
    
    return {
        "status": "success",
        "message": f"Stopped tracking session '{session_id}'"
    }


@app.get("/api/track")
def get_tracked_sessions():
    """Get all currently tracked sessions."""
    return {
        "count": tracking_manager.count(),
        "interval_minutes": tracking_manager.get_interval(),
        "sessions": tracking_manager.get_all()
    }


@app.post("/api/track/config")
def set_tracking_config(request: TrackingConfigRequest):
    """Set tracking configuration."""
    old_interval = tracking_manager.get_interval()
    tracking_manager.set_interval(request.interval_minutes)
    
    if scheduler.get_job('tracking_check'):
        scheduler.reschedule_job(
            'tracking_check',
            trigger='interval',
            minutes=request.interval_minutes
        )
    
    return {
        "status": "success",
        "message": f"Tracking interval updated from {old_interval} to {request.interval_minutes} minutes",
        "old_interval": old_interval,
        "new_interval": request.interval_minutes
    }

@app.get("/api/debug/ip_change")
async def debug_ip_change():
    """Debug endpoint to broadcast a synthetic IP change event"""
    sessions_dict = tracking_manager.get_all()
    target_session = "DEBUG_SESSION"
    for sid in sessions_dict.keys():
        target_session = sid
        break
    
    await ws_manager.broadcast({
        "type": "ip_change",
        "session": target_session,
        "old_ip": "41.242.137.88",
        "new_ip": "102.89.34.12",
        "city": "Abuja",
        "isp": "MTN Nigeria",
        "timestamp": time.time()
    })
    return {"status": "simulated", "session": target_session}

# --- WebSocket for Streaming Results ---

@app.websocket("/ws/check")
async def websocket_check_proxies(websocket: WebSocket):
    """
    WebSocket endpoint for streaming proxy check results.
    
    Client sends: {"proxies": [...], "protocol": "http"}
    Server sends: {"type": "progress", "completed": 5, "total": 100, "result": {...}}
    Server sends: {"type": "complete", "total": 100, "duration": 12.5}
    """
    await websocket.accept()
    
    try:
        # Receive check request
        data = await websocket.receive_text()
        request = json.loads(data)
        
        proxies = request.get("proxies", DEFAULT_PROXIES)
        protocol = request.get("protocol", "http")
        
        if not proxies:
            await websocket.send_json({"type": "error", "message": "No proxies provided"})
            return
        
        total = len(proxies)
        completed = 0
        start_time = time.time()
        
        # Send start message
        await websocket.send_json({
            "type": "start",
            "total": total,
            "protocol": protocol
        })
        
        # Progress callback
        async def send_progress(done: int, total_count: int, result: Dict):
            nonlocal completed
            completed = done
            await websocket.send_json({
                "type": "progress",
                "completed": completed,
                "total": total_count,
                "result": result
            })
        
        # Stream results
        async for result in check_proxies_stream(
            proxies,
            protocol=protocol,
            max_concurrent=MAX_CONCURRENT,
            timeout=PROXY_TIMEOUT
        ):
            completed += 1
            try:
                await websocket.send_json({
                    "type": "progress",
                    "completed": completed,
                    "total": total,
                    "result": result
                })
            except Exception as e:
                logger.error(f"Error sending progress: {e}")
                break
        
        # Send completion message
        duration = time.time() - start_time
        await websocket.send_json({
            "type": "complete",
            "total": total,
            "duration": round(duration, 2),
            "proxies_per_second": round(total / duration, 2) if duration > 0 else 0
        })
        
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during check")
    except json.JSONDecodeError as e:
        await websocket.send_json({"type": "error", "message": f"Invalid JSON: {e}"})
    except Exception as e:
        logger.exception(f"Error in WebSocket check: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass


@app.websocket("/ws/tracking")
async def websocket_tracking(websocket: WebSocket):
    """WebSocket endpoint for real-time tracking notifications."""
    await ws_manager.connect(websocket)
    
    try:
        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": "Connected to tracking notifications",
            "tracked_sessions": tracking_manager.count()
        }))
        
        while True:
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
                
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


# --- Scheduled Tasks ---

async def perform_tracking_checks():
    """Perform periodic checks on tracked proxies."""
    logger.info("Performing scheduled tracking checks...")
    
    tracked = tracking_manager.get_all()
    
    for session_id, data in tracked.items():
        try:
            from proxy_lib_async import check_single_proxy_async_wrapper
            
            result = await check_single_proxy_async_wrapper(
                data['proxy'],
                timeout=PROXY_TIMEOUT
            )
            
            if result and result.get('status') == 'success':
                current_ip = result.get('query')
                
                if data['last_ip'] and data['last_ip'] != current_ip:
                    event = tracking_manager.record_ip_change(
                        session_id,
                        data['last_ip'],
                        current_ip,
                        result.get('city')
                    )
                    
                    logger.warning(
                        f"[ALERT] IP Changed for {session_id}: "
                        f"{data['last_ip']} -> {current_ip}"
                    )
                    
                    await ws_manager.broadcast({
                        "type": "ip_change",
                        "session": session_id,
                        "old_ip": data['last_ip'],
                        "new_ip": current_ip,
                        "city": result.get('city'),
                        "isp": result.get('isp'),
                        "timestamp": time.time()
                    })
                
                tracking_manager.update(session_id, {
                    'last_ip': current_ip,
                    'last_check': time.time(),
                    'last_result': result
                })
        
        except Exception as e:
            logger.error(f"Error checking tracked session {session_id}: {e}")

    if tracked:
        try:
            # Tell frontend the check loop finished so it can update "Last Update"
            await ws_manager.broadcast({
                "type": "tracking_check_complete",
                "timestamp": time.time()
            })
        except Exception as e:
            logger.error(f"Error broadcasting tracking complete: {e}")


# --- Main Entry Point ---

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info"
    )
