"""`media-compost-train` — run training from a terminal.

The app is the good way to BUILD a job: picking a model, writing the dataset
query and judging a degradation variant are all things you do by looking. This
is the other half — a headless box with a GPU can take that config and run it
without ever installing the app, which is what makes the trainer a package
rather than a feature of a web server.

So the split of labour is deliberate: `config template` emits a filled-in
default to edit, `create` takes the file, and everything after that is the same
queue the browser drives.

argparse, like the main CLI (and for the same reason): the parsing is
subcommands with plain options, and typer bought convenience at the price of
two base dependencies. `rich` draws the output and stays.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.markup import escape

from . import Trainer, available, requirements
from . import paths as tp
from .spec import TrainingConfig

console = Console()


def _data_dir(data_dir: Optional[Path]) -> Path:
    if data_dir:
        return data_dir
    from media_compost import default_data_dir

    return default_data_dir()


def _trainer(data_dir: Optional[Path]) -> Trainer:
    if not available():
        # The install line is ESCAPED and the colour is not: rich reads
        # `[train]` as a style tag and drops it, which left the sentence
        # naming `pip install 'media-compost'` — the install that does not
        # bring the trainer.
        console.print(
            f"[red]training needs {', '.join(requirements())}[/red] — "
            + escape("install it with: pip install 'media-compost[train]'"),
            soft_wrap=True)
        raise SystemExit(1)
    tr = Trainer(_data_dir(data_dir))
    # Take the scheduler lease up front, not on first use: every command that
    # wants a Trainer intends to touch the training subsystem, and "the app
    # is already running it" should be one readable sentence rather than a
    # traceback out of a lazy property.
    from media_compost import TRAINING_LOCK_NAME, LockBusy, scheduler_lease

    try:
        scheduler_lease(tr.data_dir, TRAINING_LOCK_NAME)
    except LockBusy as exc:
        raise _fail(exc) from None
    # PUBLISH THE USER-ADDED MODELS, or every `user:` key in this library is
    # unknown here. `models.model_spec` resolves against a module-level cache
    # that `usermodels.refresh` fills, and the web side fills it from the
    # `user_store` dependency on any request that touches models — the CLI had
    # no equivalent, so `create` rejected a config naming a user model with
    # "unknown model 'user:tiny'", `show` could not describe such a job, and
    # `status` left it out of the model list. One call here covers every
    # command, because they all come through this function.
    from . import usermodels

    usermodels.refresh(tr.dir)      # `tr.dir` is what web/routes.py:user_store is
    return tr


def _fail(exc: Exception) -> SystemExit:
    console.print(f"[red]{exc}[/red]")
    return SystemExit(1)


# ---- setting up ---------------------------------------------------------------


def _cmd_setup(args: argparse.Namespace) -> None:
    """Build the training virtualenv (torch, diffusers, peft, …).

    Its own environment on purpose: the stack is several gigabytes, moves
    fast, and pins versions the app cannot live with. `media_compost.hub.
    setup_env` is what knows the ordering that matters — the CUDA index on
    Windows, and torch installed last so nothing drags a CPU build back over
    it. Named with `-m` so a wheel install (no checkout, no `scripts/`) can
    run it too.
    """
    from media_compost.hub.setup import SetupRun

    run = SetupRun("training",
                   ["{python} -m media_compost.hub.setup_env training"],
                   str(tp.REPO))
    shown = 0
    while run.running:
        if len(run.log) > shown:
            sys.stdout.write(run.log[shown:])
            sys.stdout.flush()
            shown = len(run.log)
        time.sleep(0.2)
    sys.stdout.write(run.log[shown:])
    if not run.ok:
        raise _fail(RuntimeError(run.error or "setup failed"))


def _cmd_status(args: argparse.Namespace) -> None:
    """Whether this machine can train, and what is running."""
    tr = _trainer(args.data_dir)
    interp = tp.interpreter()
    console.print(f"library      {tr.data_dir}")
    console.print(f"training dir {tr.dir}")
    env = interp or ("[yellow]not set up[/yellow] — run: "
                     "media-compost-train setup")
    console.print(f"environment  {env}")
    running = tr.jobs.running_uid()
    console.print(f"running      {running or '—'}")
    console.print(f"queue        {'on' if tr.jobs.queue_active() else 'off'}")


# ---- configs ------------------------------------------------------------------


def _cmd_config_template(args: argparse.Namespace) -> None:
    """Print a complete default config, to edit and hand to `create`.

    Every field with its default, not a minimal stub: the point is to see what
    can be set at all, which a five-line example does not tell you.
    """
    cfg = TrainingConfig(model=args.model)
    text = json.dumps(cfg.model_dump(mode="json"), indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        console.print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)


# ---- the queue ----------------------------------------------------------------


def _cmd_list(args: argparse.Namespace) -> None:
    """Every job, newest first."""
    tr = _trainer(args.data_dir)
    rows = tr.jobs.list_jobs()
    if not rows:
        console.print("no jobs")
        return
    for r in rows:
        step = f"{r.get('step', 0)}/{r.get('total_steps', 0)}"
        console.print(f"{r['uid']}  {r['status']:<10} {step:<12} {r.get('name') or '—'}")


def _cmd_show(args: argparse.Namespace) -> None:
    """One job's record and its config."""
    tr = _trainer(args.data_dir)
    try:
        rec = tr.jobs.get(args.uid)
        cfg = tr.jobs.read_config(args.uid)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        raise _fail(exc) from None
    console.print(json.dumps({"job": rec, "config": cfg}, indent=2))


def _cmd_create(args: argparse.Namespace) -> None:
    """Create a job from a config file (see `config template`)."""
    tr = _trainer(args.data_dir)
    try:
        spec = TrainingConfig.model_validate(
            json.loads(args.config.read_text("utf-8")))
    except Exception as exc:  # noqa: BLE001 - a bad file is a message, not a trace
        raise _fail(exc) from None
    uid = tr.jobs.create(args.name or args.config.stem, spec,
                         os.environ.get("USER", ""))
    console.print(uid)
    if args.start:
        # The job EXISTS by now, so a refusal here is a message about the
        # config and not a failure to create anything — printing a traceback
        # would suggest otherwise.
        try:
            tr.jobs.enqueue(uid)
        except Exception as exc:  # noqa: BLE001
            raise _fail(exc) from None
        tr.jobs.queue_run()
        console.print("queued — run it with: media-compost-train run")


def _cmd_start(args: argparse.Namespace) -> None:
    """Run one job now, without turning the whole queue on."""
    tr = _trainer(args.data_dir)
    try:
        tr.jobs.start_now(args.uid)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from None


def _cmd_pause(args: argparse.Namespace) -> None:
    """Checkpoint and stop a running job. It keeps its place in the queue."""
    try:
        _trainer(args.data_dir).jobs.pause(args.uid)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from None


def _cmd_cancel(args: argparse.Namespace) -> None:
    """Stop a job and take it out of the queue."""
    try:
        _trainer(args.data_dir).jobs.cancel(args.uid)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from None


def _cmd_steps(args: argparse.Namespace) -> None:
    """Change a job's total step count, including while it runs."""
    _trainer(args.data_dir).jobs.set_steps(args.uid, args.total)


def _cmd_queue_run(args: argparse.Namespace) -> None:
    """Start working through the queue, and keep going as jobs finish."""
    _trainer(args.data_dir).jobs.queue_run()


def _cmd_queue_stop(args: argparse.Namespace) -> None:
    """Stop taking new jobs. Anything already running keeps running."""
    _trainer(args.data_dir).jobs.queue_stop()


def _cmd_run(args: argparse.Namespace) -> None:
    """Work through the queue, here, until you stop it.

    The scheduler is a THREAD, so it lives exactly as long as the process
    holding it — which is why `create --start` only queues: it turns the
    switch on and then exits, taking the tick with it. This is the command
    that actually runs things on a headless box, and the one you put under
    systemd.

    Ctrl-C PAUSES whatever is running rather than killing it. A run is hours
    of GPU work; the difference between a checkpoint and nothing is the whole
    value of stopping cleanly.
    """
    tr = _trainer(args.data_dir)
    if tp.interpreter() is None:
        raise _fail(RuntimeError(
            "the training environment is not set up — run: "
            "media-compost-train setup"))
    tr.jobs.queue_run()
    console.print("[green]queue running[/green] — Ctrl-C to pause and stop")
    last = None
    try:
        while True:
            rows = tr.jobs.list_jobs()
            active = [r for r in rows if r.get("status") in tp.ACTIVE_STATUSES]
            now = tuple((r["uid"], r["status"], r.get("step"), r.get("phase"))
                        for r in active)
            if now != last:
                for uid, status, step, phase in now:
                    console.print(f"{uid}  {status:<9} step {step}  {phase}")
                last = now
            if not active:
                if args.once:
                    console.print("queue drained")
                    return
                time.sleep(2)
                continue
            time.sleep(2)
    except KeyboardInterrupt:
        console.print("\npausing…")
        tr.jobs.queue_stop()
        running = tr.jobs.running_uid()
        if running:
            try:
                tr.jobs.pause(running)
            except Exception:  # noqa: BLE001 - already stopping
                pass
            # Give the trainer time to write its checkpoint; it is the reason
            # we are waiting at all.
            for _ in range(120):
                if tr.jobs.get(running).get("status") != "pausing":
                    break
                time.sleep(1)
        console.print("stopped")


def _cmd_log(args: argparse.Namespace) -> None:
    """A job's log, optionally followed."""
    tr = _trainer(args.data_dir)
    path = tp.log_path(tp.job_dir(tr.dir, args.uid))
    shown = 0
    while True:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if len(text) > shown:
            sys.stdout.write(text[shown:])
            sys.stdout.flush()
            shown = len(text)
        if not args.follow:
            return
        try:
            rec = tr.jobs.get(args.uid)
        except Exception:  # noqa: BLE001 - a deleted job ends the follow
            return
        if rec.get("status") not in tp.ACTIVE_STATUSES:
            return
        time.sleep(0.5)


def _cmd_watch(args: argparse.Namespace) -> None:
    """Follow a job to its end, printing each change of state.

    What a terminal actually wants from a run that takes hours: not a progress
    bar redrawn sixty times a second, but a line whenever something changes.
    """
    tr = _trainer(args.data_dir)
    last = None
    while True:
        try:
            rec = tr.jobs.get(args.uid)
        except Exception as exc:  # noqa: BLE001
            raise _fail(exc) from None
        now = (rec.get("status"), rec.get("step"), rec.get("phase"),
               rec.get("phase_note"))
        if now != last:
            console.print(f"{now[0]:<10} step {now[1]}  {now[2]} {now[3]}".rstrip())
            last = now
        if rec.get("status") not in tp.ACTIVE_STATUSES:
            if rec.get("message"):
                console.print(rec["message"])
            return
        time.sleep(2)


# ---- the parser ----------------------------------------------------------------


def _add_data_dir(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("-d", "--data-dir", type=Path, default=None, metavar="PATH",
                    help="The library. Defaults to MEDIA_COMPOST_DATA, "
                         "else ./_data")


def _sub(subparsers, name: str, func) -> argparse.ArgumentParser:
    doc = (func.__doc__ or "").strip()
    # The command list shows the docstring's first SENTENCE, not its first
    # physical line — a wrapped sentence cut at the line break reads as
    # "...sidecar from the database (the DB is".
    first = " ".join(doc.split("\n\n")[0].split())
    short = first.split(". ")[0].rstrip(".") + "."
    sp = subparsers.add_parser(
        name, help=short, description=doc,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sp.set_defaults(func=func)
    return sp


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="media-compost-train",
                                description="Media Compost — training")
    sub = p.add_subparsers(metavar="COMMAND", required=True)

    _sub(sub, "setup", _cmd_setup)
    _add_data_dir(_sub(sub, "status", _cmd_status))

    cfg = sub.add_parser("config", help="Job configuration files")
    csub = cfg.add_subparsers(metavar="SUBCOMMAND", required=True)
    sp = _sub(csub, "template", _cmd_config_template)
    sp.add_argument("--model", default="sd15", help="Base model key")
    sp.add_argument("-o", "--out", type=Path, default=None)

    _add_data_dir(_sub(sub, "list", _cmd_list))

    sp = _sub(sub, "show", _cmd_show)
    sp.add_argument("uid")
    _add_data_dir(sp)

    sp = _sub(sub, "create", _cmd_create)
    sp.add_argument("config", type=Path)
    sp.add_argument("-n", "--name", default="")
    sp.add_argument("--start", action="store_true",
                    help="Queue it and turn the queue on")
    _add_data_dir(sp)

    for name, func in (("start", _cmd_start), ("pause", _cmd_pause),
                       ("cancel", _cmd_cancel)):
        sp = _sub(sub, name, func)
        sp.add_argument("uid")
        _add_data_dir(sp)

    sp = _sub(sub, "steps", _cmd_steps)
    sp.add_argument("uid")
    sp.add_argument("total", type=int)
    _add_data_dir(sp)

    q = sub.add_parser("queue", help="The run switch")
    qsub = q.add_subparsers(metavar="SUBCOMMAND", required=True)
    _add_data_dir(_sub(qsub, "run", _cmd_queue_run))
    _add_data_dir(_sub(qsub, "stop", _cmd_queue_stop))

    sp = _sub(sub, "run", _cmd_run)
    sp.add_argument("--once", action="store_true",
                    help="Stop when the queue drains")
    _add_data_dir(sp)

    sp = _sub(sub, "log", _cmd_log)
    sp.add_argument("uid")
    sp.add_argument("-f", "--follow", action="store_true")
    _add_data_dir(sp)

    sp = _sub(sub, "watch", _cmd_watch)
    sp.add_argument("uid")
    _add_data_dir(sp)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
