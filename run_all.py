"""One Render Web Service supervising the HTTP website and Discord bot."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


ROOT = Path(__file__).resolve().parent


def stop_process(process, timeout=10):
    if process.poll() is not None:
        return
    try:
        if os.name == 'nt':
            # Only processes created by this supervisor; include the Windows venv launcher child.
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)
    except ProcessLookupError:
        pass


def supervise(commands, stopped=None, launch=None, stop=None):
    stopped = stopped if stopped is not None else threading.Event()
    launch = launch if launch is not None else subprocess.Popen
    stop = stop if stop is not None else stop_process
    children = []
    options = dict(cwd=str(ROOT))
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    try:
        for name, command in commands:
            if stopped.is_set():
                break
            children.append((name, launch(command, **options)))
            print(f'Started {name}.', flush=True)
        while not stopped.is_set():
            for name, process in children:
                code = process.poll()
                if code is not None:
                    print(f'{name} exited with status {code}; stopping both services.', flush=True)
                    return 1
            stopped.wait(.25)
        return 0
    finally:
        for _, process in reversed(children):
            try:
                stop(process)
            except Exception as error:
                print(f'Child shutdown error: {type(error).__name__}',flush=True)


def main():
    # Reuse local dotenv handling; on Render only real service environment is read.
    import storage  # noqa: F401
    from auth_service import current_website_origin
    if not os.getenv('DISCORD_TOKEN'):
        raise SystemExit('Missing DISCORD_TOKEN: set it in Render Environment.')
    if not os.getenv('DATABASE_URL'):
        raise SystemExit('Missing DATABASE_URL: set it in Render Environment.')
    if os.getenv('RENDER') == 'true' and not os.getenv('FLASK_SECRET_KEY'):
        raise SystemExit('Missing FLASK_SECRET_KEY: set it in Render Environment.')
    current_website_origin()
    stopped = threading.Event()
    def shutdown(signum, frame):
        stopped.set()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    commands = [(name, [sys.executable, '-u', str(ROOT / script)])
                for name, script in [('website', 'app.py'), ('Discord bot', 'discord_bot.py')]]
    return supervise(commands, stopped)


if __name__ == '__main__':
    raise SystemExit(main())
