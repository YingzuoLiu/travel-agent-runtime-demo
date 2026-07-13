from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolExecutionStatus(str, Enum):
    COMPLETED = "completed"
    DENIED = "denied"
    INVALID_INPUT = "invalid_input"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
