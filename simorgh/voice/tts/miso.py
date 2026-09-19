"""MisoTTS 8B (Miso Labs, open weights): a Sesame-CSM-style text-to-
dialogue model -- 8B backbone, Mimi codec, 16 GB of bfloat16 weights --
that reads feeling from the words and the context rather than from a
dial; a reference WAV clones a voice. Its repository asks for a 24 GB
GPU; here it is tried on Apple's MPS or the CPU, and the server says
which and how long it took, so the creator can decide (2026-09-13:
"let's build the system for both ... and decide later"). Runs in a
Python 3.10 venv with the MisoTTS checkout on its path."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .subproc import DEFAULT_VENV_DIR, SubprocessSynthesiser, create_venv, engine_available

REPO_URL = "https://github.com/MisoLabsAI/MisoTTS.git"
DEFAULT_REPO = "workspace/voice/engines/MisoTTS"

#: The module the readiness probe imports, and the reason it is not
#: `torch`. It was `torch` until 2026-09-16, which is a DEPENDENCY, not
#: this engine: torch imported perfectly while the engine itself could
#: not load at all (a numpy 2 ABI break further down the chain, in
#: torchtune -> datasets -> pyarrow). So `available()` answered True for
#: an engine that could not speak a word, `open_synthesiser` saw no
#: problem to fall back from, the refusal guard in `service._set` never
#: fired, `tts = "miso"` was written into simorgh.toml, and Sim said
#: "engines reopened; listening again" -- while every turn went on being
#: spoken by Kokoro. The creator, that evening: "misotts doesn't work".
#:
#: An engine is asked about ITSELF. `generator` is the MisoTTS
#: checkout's own top-level module (its editable install puts it on the
#: path, so no PYTHONPATH is needed), and importing it exercises the
#: whole chain that actually has to work.
ENGINE_MODULE = "generator"


#: Upstream hardcodes Meta's own tokenizer repo, which is `gated=manual`
#: -- every download waits on a human at Meta, so the engine 403s at load
#: and never speaks a word. `workspace/` is gitignored, so a patch to the
#: checkout cannot be committed and a fresh `voice models miso` would
#: quietly restore the gated name. So the override is re-applied here,
#: after every clone.
_TOKENIZER_LINE = '    tokenizer_name = "meta-llama/Llama-3.2-1B"'
_TOKENIZER_PATCH = (
    "    # Overridable (Simorgh): Meta's repo is gated=manual, so upstream's\n"
    "    # hardcoded name 403s at load. MISO_TOKENIZER names an ungated\n"
    "    # mirror of the same Llama 3.2 1B tokenizer.\n"
    "    import os as _os\n"
    '    tokenizer_name = _os.environ.get("MISO_TOKENIZER") or "meta-llama/Llama-3.2-1B"'
)


def allow_an_ungated_tokenizer(repo: str | Path, *, log=print) -> str:
    """Make the checkout's tokenizer name honour `MISO_TOKENIZER`.

    Returns "" when done or already done, else why not. Never raises: a
    checkout that has changed upstream is a thing to report, not a
    crash during an install.
    """
    source = Path(repo) / "generator.py"
    try:
        text = source.read_text()
    except OSError as exc:
        return f"could not read {source}: {exc}"
    if "MISO_TOKENIZER" in text:
        return ""
    if _TOKENIZER_LINE not in text:
        return (f"{source} no longer has the hardcoded tokenizer line; MisoTTS will ask "
                "Meta's gated repo unless it has been granted access")
    try:
        source.write_text(text.replace(_TOKENIZER_LINE, _TOKENIZER_PATCH, 1))
    except OSError as exc:
        return f"could not patch {source}: {exc}"
    log("  pointed the tokenizer at MISO_TOKENIZER (Meta's own repo is gated) ...")
    return ""


def available(venv_dir: str = DEFAULT_VENV_DIR, repo: str = DEFAULT_REPO) -> tuple[bool, str]:
    if not (Path(repo) / "generator.py").is_file():
        return False, f"needs the MisoTTS checkout at {repo} (`voice models miso` clones it)"
    return engine_available("miso", ENGINE_MODULE, venv_dir)


def install(venv_dir: str = DEFAULT_VENV_DIR, repo: str = DEFAULT_REPO, *, log=print):
    import subprocess

    repo_path = Path(repo)
    if not (repo_path / "generator.py").is_file():
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        log(f"  cloning {REPO_URL} into {repo_path} ...")
        done = subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(repo_path)], capture_output=True, text=True, timeout=600)
        if done.returncode != 0:
            return None, f"could not clone MisoTTS: {(done.stderr or done.stdout).strip()[-300:]}"
    why = allow_an_ungated_tokenizer(repo_path, log=log)
    if why:
        log(f"  note: {why}")
    py, problem = create_venv(venv_dir, "miso", python="3.10", editable=str(repo_path), log=log)
    if py is None:
        return py, problem
    # MisoTTS pulls torchtune, which imports `datasets`, which imports
    # pyarrow -- and the wheels for pyarrow 14 and torch 2.4 are built
    # against numpy 1.x. Resolution picks numpy 2 anyway, and the whole
    # chain then dies at import with "_ARRAY_API not found" /
    # "numpy.core.multiarray failed to import". The engine installed,
    # reported success, and could never open (the creator ran `voice set
    # tts miso` on 2026-09-16 and got Kokoro, correctly refused).
    #
    # Pinned AFTER the editable install, because that install is what
    # drags numpy 2 back in.
    log("  pinning numpy<2 (pyarrow/torch wheels are built against it) ...")
    import subprocess

    uv = shutil.which("uv")
    cmd = ([uv, "pip", "install", "--python", str(py), "numpy<2"] if uv
           else [str(py), "-m", "pip", "install", "-q", "numpy<2"])
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if done.returncode != 0:
        return None, f"could not pin numpy<2: {(done.stderr or done.stdout).strip()[-300:]}"
    return py, ""


class MisoSynthesiser(SubprocessSynthesiser):
    name = "miso"
    module = ENGINE_MODULE
    server = "miso_server.py"
    #: Torch 2.4 has no MPS kernel for `aten::unfold_backward`, and
    #: MisoTTS's decoder uses it -- so synthesis raised
    #: NotImplementedError on Apple Silicon, no audio was ever written,
    #: and every layer above still reported a successful `spoken
    #: (miso)`. This runs that one operator on the CPU.
    #:
    #: Measured 2026-09-16: without it, no sound at all; with it, 2.32 s
    #: of speech in 103 s -- 44x real time. That is why Miso belongs in
    #: the expressive lane and never in a spoken turn.
    extra_env = {"PYTORCH_ENABLE_MPS_FALLBACK": "1"}
    load_timeout_s = 1800.0   # 16 GB of weights the first time

    def __init__(self, config) -> None:
        self._repo = str(getattr(config, "miso_repo", "workspace/voice/engines/MisoTTS") or DEFAULT_REPO)
        ok, why = available(getattr(config, "venv_dir", DEFAULT_VENV_DIR), self._repo)
        if not ok:
            raise ImportError(why)
        super().__init__(config, venv_dir=getattr(config, "venv_dir", DEFAULT_VENV_DIR),
                         reference=str(getattr(config, "miso_reference", "") or ""),
                         timeout_s=float(getattr(config, "expressive_timeout_s", 180.0)) * 3)
        self._device = str(getattr(config, "miso_device", "") or "")
        os.environ["MISO_REPO"] = str(Path(self._repo).resolve())
        tokenizer = str(getattr(config, "miso_tokenizer", "unsloth/Llama-3.2-1B") or "")
        if tokenizer:
            os.environ["MISO_TOKENIZER"] = tokenizer
        if self._device:
            os.environ["MISO_DEVICE"] = self._device

    def params_for(self, tone: str) -> dict:
        # Miso takes no emotion dial: the feeling is in the words. A little
        # more temperature for the lively tones, less for the calm ones.
        temperature = {"bright": 1.0, "playful": 1.0, "calm": 0.7, "sorry": 0.7, "serious": 0.75}.get((tone or "").lower(), 0.9)
        return {"speaker": 0, "temperature": temperature, "max_audio_length_ms": 30_000}


__all__ = ["allow_an_ungated_tokenizer", "DEFAULT_REPO", "MisoSynthesiser", "REPO_URL", "available", "install"]
