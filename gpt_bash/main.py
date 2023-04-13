"""
Fastapi app

This is a web server that executes bash commands and returns the output.
"""

import asyncio
import base64
import logging
from pathlib import Path
from typing import Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status, UploadFile, File
from pydantic import BaseModel, Field, validator
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

app = FastAPI(
    title="OpenAI Shell plugin",
    description="This is a web server that executes shell commands and returns the output.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for chat.openai.com
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chat.openai.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],

)

# templates = Jinja2Templates(directory="templates")
# app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/.well-known", StaticFiles(directory="./.well-known"), name="well-known")


class Command(BaseModel):
    """
    The request body for the / command
    """

    command: str = Field(..., min_length=1, max_length=2048, example="ls -l", description="Command to execute. It must be a single JSON string, no concatenation or new lines allowed!")
    cwd: Optional[str] = Field(None, min_length=1, max_length=2048, example="/tmp",
                               description="Current working directory")
    env: Optional[Dict[str, str]] = Field(None, example={"FOO": "BAR"}, description="Environment variables")
    timeout: Optional[int] = Field(None, ge=1, le=86400, example=60, description="Timeout in seconds")
    shell: Optional[bool] = Field(True, example=True, description="Execute command in a shell")
    stdin: Optional[str] = Field(None, min_length=1, max_length=2048, example="Hello World",
                                 description="Standard input to pass to the command")

    @validator("cwd")
    def cwd_must_be_safe(cls, value: str) -> str:
        """
        Make sure the cwd is safe to execute
        """
        # pylint: disable=unused-argument
        if not value:
            raise ValueError("Must provide a cwd")
        if ";" in value:
            raise ValueError("Semicolons are not allowed")
        if "|" in value:
            raise ValueError("Pipes are not allowed")
        if "&" in value:
            raise ValueError("Ampersands are not allowed")
        if ">" in value:
            raise ValueError("Redirection is not allowed")
        return value

    @validator("env")
    def env_must_be_safe(cls, value: Dict[str, str]) -> Dict[str, str]:
        """
        Make sure the env is safe to execute
        """
        # pylint: disable=unused-argument
        for key, val in value.items():
            if ";" in key:
                raise ValueError("Semicolons are not allowed")
            if "|" in key:
                raise ValueError("Pipes are not allowed")
            if "&" in key:
                raise ValueError("Ampersands are not allowed")
            if ">" in key:
                raise ValueError("Redirection is not allowed")
            if ";" in val:
                raise ValueError("Semicolons are not allowed")
            if "|" in val:
                raise ValueError("Pipes are not allowed")
            if "&" in val:
                raise ValueError("Ampersands are not allowed")
            if ">" in val:
                raise ValueError("Redirection is not allowed")
        return value

    @validator("stdin")
    def stdin_must_be_safe(cls, value: str) -> str:
        """
        Make sure the stdin is safe to execute
        """
        if ";" in value:
            raise ValueError("Semicolons are not allowed")
        if "|" in value:
            raise ValueError("Pipes are not allowed")
        if "&" in value:
            raise ValueError("Ampersands are not allowed")
        if ">" in value:
            raise ValueError("Redirection is not allowed")
        return value


class CommandResponse(BaseModel):
    """
    The response body for the / command
    """
    stdout: str = Field(..., min_length=0, max_length=1024 * 1024, description="Standard output from the command")
    stderr: str = Field(..., min_length=0, max_length=1024 * 1024, description="Standard error from the command")
    returncode: int = Field(..., ge=0, le=255, description="Return code from the command")


# Document exceptions in OpenAPI
@app.post("/command",
          response_model=CommandResponse,
          status_code=200,
          tags=["commands"],
          summary="Execute a command",
          description="Execute a command and return the output",
          response_description="The output from the command",
          )
async def post_command(request: Request, command: Command) -> CommandResponse:
    """
    Execute a command and return the output
    """
    logging.info("Received request: %s", command)

    if command.shell:
        command_ = ["/bin/bash", "-c", command.command]
    else:
        command_ = command.command.split()

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            command_[0],
            *command_[1:],
            cwd=command.cwd,
            env=command.env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # loop=asyncio.get_running_loop(),

        )
        # await or timeout
        # stdout, stderr = proc.communicate(input=command.stdin.encode("utf-8"))
        if command.stdin:
            proc.stdin.write(command.stdin.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        stdout, stderr = await asyncio.wait_for(
            # proc.communicate(command.stdin.encode("utf-8")),
            proc.communicate(),
            timeout=command.timeout,
        )
    except asyncio.TimeoutError:
        if proc is not None:
            proc.kill()
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="Command timed out",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    return CommandResponse(
        stdout=stdout.decode("utf-8"),
        stderr=stderr.decode("utf-8") if stderr else "",
        returncode=proc.returncode,
    )


@app.post("/files/{file_path:path}",
          tags=["files"],
          summary="Upload file to path",
          description="Upload file to path",
          )
async def upsert_file(
        file_path: str,
        contents: str,
):
    """
    Upload a file and saves it in path. Input must be a valid JSON!.
    """
    # Read the file
    file_path = file_path
    data = contents
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file data",
        )

    # Save the file
    try:
        with open(file_path, "w") as file:
            file.write(data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return {"status": "ok"}


@app.get("/files/{file_path:path}",
         response_class=FileResponse, tags=["files"],
         summary="Get file from path",
         description="Get file from path"
         )
async def get_file(file_path: str):
    """
        Get file from path.
    """
    path = Path("/" + file_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    return FileResponse(path)


if __name__ == '__main__':
    # Enable logging in the console
    logging.basicConfig(level=logging.INFO)

    # Run the app in HTTPS mode
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        ssl_keyfile="key.pem",
        ssl_certfile="cert.pem",
        reload=True,
    )

# Example usage with curl displaying the response code and body
# $ curl -w '\n%{http_code}\n' -X POST -H "Content-Type: application/json" -d '{"command": "ls -l", "cwd": "/tmp", "timeout": 5}' http://localhost:8000/

# Example for uploading a file
# $ curl -w '\n%{http_code}\n' -X POST -F "file=@/etc/hosts" http://localhost:8000/upsert-file
