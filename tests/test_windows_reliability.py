import queue
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import windows_app


class _Value:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _FailOnValue(_Value):
    def __init__(self, rejected: str) -> None:
        super().__init__("Ready")
        self.rejected = rejected

    def set(self, value: str) -> None:
        if value == self.rejected:
            raise RuntimeError("status update failed")
        super().set(value)


class _Progress:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self, _interval: int) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _Button:
    def __init__(self, state: str = "normal") -> None:
        self.state = state

    def cget(self, name: str) -> str:
        if name != "state":
            raise KeyError(name)
        return self.state

    def config(self, *, state: str) -> None:
        self.state = state


class _FailingRestoreButton(_Button):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def config(self, *, state: str) -> None:
        if state == "normal":
            raise self.error
        super().config(state=state)


class _Root:
    def __init__(self) -> None:
        self.destroyed = False
        self.clipboard = ""
        self.pending_callbacks = []
        self.after_thread_ids = []

    def after(self, _delay: int, callback) -> str:
        self.after_thread_ids.append(threading.get_ident())
        self.pending_callbacks.append(callback)
        return f"after-{len(self.pending_callbacks)}"

    def run_pending(self) -> None:
        callback = self.pending_callbacks.pop(0)
        callback()

    def destroy(self) -> None:
        self.destroyed = True

    def clipboard_clear(self) -> None:
        self.clipboard = ""

    def clipboard_append(self, value: str) -> None:
        self.clipboard += value


class _ImmediateThread:
    def __init__(self, *, target, name: str, daemon: bool) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon
        self.alive = False

    def start(self) -> None:
        self.alive = True
        try:
            self.target()
        finally:
            self.alive = False

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout=None) -> None:
        return


class _FailingThread(_ImmediateThread):
    def start(self) -> None:
        raise RuntimeError("thread start failed")


class _FailingAfterRoot(_Root):
    def after(self, _delay: int, callback) -> str:
        raise RuntimeError("Tk scheduling failed")


class _SecondAfterFailsRoot(_Root):
    def after(self, _delay: int, callback) -> str:
        if self.after_thread_ids:
            raise RuntimeError("Tk rescheduling failed")
        return super().after(_delay, callback)


class _ControllableThread(_ImmediateThread):
    def start(self) -> None:
        self.alive = True

    def join(self, timeout=None) -> None:
        raise AssertionError("The Tk thread must never wait for this worker")


class _FinishDuringLivenessRaceQueue:
    """Publish a finish immediately after the poller's first empty read."""

    def __init__(self, worker, payload) -> None:
        self.worker = worker
        self.payload = payload
        self.events = queue.Queue()
        self.first_read = True

    def get_nowait(self):
        if self.first_read:
            self.first_read = False
            self.events.put(("finish", self.payload))
            self.worker.alive = False
            raise queue.Empty
        return self.events.get_nowait()


def _bare_app() -> windows_app.RatTrapApp:
    app = windows_app.RatTrapApp.__new__(windows_app.RatTrapApp)
    app.root = _Root()
    app.busy = False
    app._closing = False
    app._diagnostics_closed = False
    app._task_events = None
    app._task_token = None
    app._worker_thread = None
    app._task_status_lock = threading.Lock()
    app._pending_task_status = None
    app._task_monitor_failed = False
    app._active_operation = None
    app.diagnostics = mock.Mock()
    app.diagnostics.available = True
    app.diagnostics.record.return_value = "RT-1111111111"
    app.diagnostics.record_exception.return_value = "RT-ABCDEF1234"
    app.action_buttons = [_Button()]
    app._saved_action_states = {}
    app.status_text = _Value("Ready")
    app.progress = _Progress()
    return app


class WindowsLifecycleTests(unittest.TestCase):
    def test_close_is_blocked_while_operation_is_active(self) -> None:
        app = _bare_app()
        app.busy = True

        with mock.patch.object(windows_app.messagebox, "showwarning") as warning:
            app._request_close()

        self.assertFalse(app.root.destroyed)
        self.assertFalse(app._closing)
        app.diagnostics.close.assert_not_called()
        app.diagnostics.record.assert_called_once_with(
            "app.close.blocked",
            details={
                "component": "windows_ui",
                "status": "busy",
            },
        )
        self.assertIn("still working", warning.call_args.args[1])

    def test_idle_close_flushes_diagnostics_and_destroys_window(self) -> None:
        app = _bare_app()

        app._request_close()
        app._request_close()

        self.assertTrue(app.root.destroyed)
        self.assertTrue(app._closing)
        app.diagnostics.close.assert_called_once_with()
        app.diagnostics.record.assert_called_once_with(
            "app.closed",
            details={
                "component": "windows_ui",
                "status": "complete",
            },
        )

    def test_worker_failure_restores_controls_and_uses_safe_reference(self) -> None:
        app = _bare_app()
        completed = mock.Mock()
        private_error = ValueError(
            r"C:\Users\Martin\Documents\private.txt password=hunter2"
        )

        def work() -> object:
            raise private_error

        with (
            mock.patch.object(
                windows_app.threading,
                "Thread",
                _ImmediateThread,
            ),
            mock.patch.object(windows_app.messagebox, "showerror") as showerror,
        ):
            app._run_task("Creating archive...", work, completed)
            app.root.run_pending()

        self.assertFalse(app.busy)
        self.assertTrue(app.progress.started)
        self.assertTrue(app.progress.stopped)
        self.assertEqual(app.action_buttons[0].state, "normal")
        self.assertEqual(app.status_text.get(), "Operation failed")
        completed.assert_not_called()
        app.diagnostics.record_exception.assert_called_once_with(
            "ui.worker.failed",
            private_error,
            details={
                "component": "windows_ui",
                "operation": "archive_create",
                "stage": "worker",
                "status": "failed",
            },
        )
        visible_message = showerror.call_args.args[1]
        self.assertIn("RT-ABCDEF1234", visible_message)
        self.assertNotIn("Martin", visible_message)
        self.assertNotIn("hunter2", visible_message)

    def test_completion_callback_failure_is_caught_after_controls_restore(
        self,
    ) -> None:
        app = _bare_app()
        completion_error = RuntimeError("private completion details")

        def done(_result: object) -> None:
            self.assertFalse(app.busy)
            self.assertEqual(app.action_buttons[0].state, "normal")
            raise completion_error

        with (
            mock.patch.object(
                windows_app.threading,
                "Thread",
                _ImmediateThread,
            ),
            mock.patch.object(windows_app.messagebox, "showerror"),
        ):
            app._run_task("Loading details...", lambda: object(), done)
            app.root.run_pending()

        self.assertEqual(app.status_text.get(), "Operation failed")
        app.diagnostics.record_exception.assert_called_once_with(
            "ui.completion.failed",
            completion_error,
            details={
                "component": "windows_ui",
                "operation": "background_task",
                "stage": "completion",
                "status": "failed",
            },
        )

    def test_success_callback_can_replace_ready_status(self) -> None:
        app = _bare_app()

        def done(_result: object) -> None:
            app.status_text.set("Repository refreshed")

        with mock.patch.object(
            windows_app.threading,
            "Thread",
            _ImmediateThread,
        ):
            app._run_task("Refreshing...", lambda: object(), done)
            app.root.run_pending()

        self.assertFalse(app.busy)
        self.assertEqual(app.status_text.get(), "Repository refreshed")

    def test_done_callback_can_start_a_new_task_without_false_ready_status(
        self,
    ) -> None:
        app = _bare_app()
        second_done = mock.Mock()

        def first_done(_result: object) -> None:
            app._run_task(
                "Second operation...",
                lambda: "second",
                second_done,
            )

        with mock.patch.object(
            windows_app.threading,
            "Thread",
            _ImmediateThread,
        ):
            app._run_task("First operation...", lambda: "first", first_done)
            app.root.run_pending()
            self.assertTrue(app.busy)
            self.assertEqual(app.status_text.get(), "Second operation...")
            app.root.run_pending()

        self.assertFalse(app.busy)
        second_done.assert_called_once_with("second")

    def test_real_worker_thread_uses_queue_not_tk(self) -> None:
        app = _bare_app()
        main_thread = threading.get_ident()
        worker_threads = []
        completion_threads = []

        def work() -> object:
            worker_threads.append(threading.get_ident())
            app._queue_task_status("Worker progress")
            return "complete"

        def done(_result: object) -> None:
            completion_threads.append(threading.get_ident())

        app._run_task("Working...", work, done)
        worker = app._worker_thread
        self.assertIsNotNone(worker)
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        app.root.run_pending()

        self.assertEqual(worker_threads, [worker.ident])
        self.assertNotEqual(worker.ident, main_thread)
        self.assertEqual(completion_threads, [main_thread])
        self.assertEqual(app.root.after_thread_ids, [main_thread])

    def test_setup_failure_restores_idle_state(self) -> None:
        app = _bare_app()
        setup_error = RuntimeError("progress setup failed")
        app.progress.start = mock.Mock(side_effect=setup_error)

        with mock.patch.object(windows_app.messagebox, "showerror"):
            app._run_task("Starting...", lambda: object(), mock.Mock())

        self.assertFalse(app.busy)
        self.assertEqual(app.action_buttons[0].state, "normal")
        app.diagnostics.record_exception.assert_called_once_with(
            "ui.worker.setup_failed",
            setup_error,
            details={
                "component": "windows_ui",
                "operation": "background_task",
                "stage": "setup",
                "status": "failed",
            },
        )

    def test_thread_start_failure_restores_idle_state(self) -> None:
        app = _bare_app()

        with (
            mock.patch.object(
                windows_app.threading,
                "Thread",
                _FailingThread,
            ),
            mock.patch.object(windows_app.messagebox, "showerror"),
        ):
            app._run_task("Starting...", lambda: object(), mock.Mock())

        self.assertFalse(app.busy)
        self.assertEqual(app.action_buttons[0].state, "normal")
        self.assertIsNone(app._worker_thread)
        self.assertIsNone(app._task_events)
        self.assertIsNone(app._task_token)
        self.assertEqual(
            app.diagnostics.record_exception.call_args.args[0],
            "ui.worker.start_failed",
        )

    def test_stale_poller_cannot_consume_a_later_task(self) -> None:
        app = _bare_app()

        with (
            mock.patch.object(
                windows_app.threading,
                "Thread",
                _FailingThread,
            ),
            mock.patch.object(windows_app.messagebox, "showerror"),
        ):
            app._run_task("Failed start...", lambda: object(), mock.Mock())

        completed = mock.Mock()
        with mock.patch.object(
            windows_app.threading,
            "Thread",
            _ImmediateThread,
        ):
            app._run_task("New task...", lambda: "new", completed)
            app.root.run_pending()
            self.assertTrue(app.busy)
            app.root.run_pending()

        self.assertFalse(app.busy)
        completed.assert_called_once_with("new")

    def test_tk_schedule_failure_restores_idle_state(self) -> None:
        app = _bare_app()
        app.root = _FailingAfterRoot()

        with mock.patch.object(windows_app.messagebox, "showerror"):
            app._run_task("Starting...", lambda: object(), mock.Mock())

        self.assertFalse(app.busy)
        self.assertEqual(app.action_buttons[0].state, "normal")
        self.assertIsNone(app._worker_thread)
        self.assertIsNone(app._task_events)
        self.assertIsNone(app._task_token)
        self.assertEqual(
            app.diagnostics.record_exception.call_args.args[0],
            "ui.worker.schedule_failed",
        )

    def test_poll_reschedule_failure_never_joins_active_worker(self) -> None:
        app = _bare_app()
        app.root = _SecondAfterFailsRoot()

        with (
            mock.patch.object(
                windows_app.threading,
                "Thread",
                _ControllableThread,
            ),
            mock.patch.object(windows_app.messagebox, "showerror") as showerror,
        ):
            app._run_task("Working...", lambda: object(), mock.Mock())
            app.root.run_pending()

        self.assertTrue(app.busy)
        self.assertTrue(app._task_monitor_failed)
        self.assertIn("still running", app.status_text.get())
        self.assertIn("lost the interface monitor", showerror.call_args.args[1])

        app._worker_thread.alive = False
        app._request_close()

        self.assertFalse(app.busy)
        self.assertTrue(app.root.destroyed)
        self.assertEqual(app.action_buttons[0].state, "normal")

    def test_finish_published_during_liveness_check_is_not_discarded(
        self,
    ) -> None:
        app = _bare_app()
        app.busy = True
        app._active_operation = "background_task"
        token = object()
        app._task_token = token
        worker = _ControllableThread(
            target=lambda: None,
            name="race-worker",
            daemon=True,
        )
        worker.alive = True
        app._worker_thread = worker
        completed = mock.Mock()
        app._task_events = _FinishDuringLivenessRaceQueue(
            worker,
            ("complete", completed, None),
        )

        app._poll_task_events(token)

        self.assertFalse(app.busy)
        self.assertIsNone(app._task_events)
        self.assertIsNone(app._worker_thread)
        completed.assert_called_once_with("complete")
        self.assertFalse(
            any(
                call.args and call.args[0] == "ui.worker.result_missing"
                for call in app.diagnostics.record_exception.call_args_list
            )
        )

    def test_progress_render_failure_cannot_strand_busy_state(self) -> None:
        app = _bare_app()
        app.status_text = _FailOnValue("Worker progress")
        completed = mock.Mock()

        def work() -> object:
            app._queue_task_status("Worker progress")
            return object()

        with (
            mock.patch.object(
                windows_app.threading,
                "Thread",
                _ImmediateThread,
            ),
            mock.patch.object(windows_app.messagebox, "showerror"),
        ):
            app._run_task("Working...", work, completed)
            app.root.run_pending()

        self.assertFalse(app.busy)
        self.assertFalse(app._task_monitor_failed)
        completed.assert_not_called()
        self.assertEqual(
            app.diagnostics.record_exception.call_args.args[0],
            "ui.worker.poll_failed",
        )

    def test_control_restore_failure_is_surfaced_and_not_successful(
        self,
    ) -> None:
        app = _bare_app()
        restore_error = RuntimeError("button restore failed")
        app.action_buttons = [_FailingRestoreButton(restore_error)]
        completed = mock.Mock()

        with (
            mock.patch.object(
                windows_app.threading,
                "Thread",
                _ImmediateThread,
            ),
            mock.patch.object(windows_app.messagebox, "showerror") as showerror,
        ):
            app._run_task("Working...", lambda: object(), completed)
            app.root.run_pending()

        self.assertFalse(app.busy)
        self.assertEqual(app.status_text.get(), "Operation failed")
        completed.assert_not_called()
        app.diagnostics.record_exception.assert_called_once_with(
            "ui.controls.restore_failed",
            restore_error,
            details={
                "component": "windows_ui",
                "operation": "background_task",
                "stage": "completion",
                "status": "failed",
            },
        )
        self.assertIn("RT-ABCDEF1234", showerror.call_args.args[1])

    def test_tk_callback_exception_is_caught_without_exposing_message(
        self,
    ) -> None:
        app = _bare_app()
        callback_error = ValueError("password=private-value")

        with mock.patch.object(windows_app.messagebox, "showerror") as showerror:
            app._report_callback_exception(
                ValueError,
                callback_error,
                None,
            )

        app.diagnostics.record_exception.assert_called_once_with(
            "ui.callback.failed",
            callback_error,
            details={
                "component": "windows_ui",
                "stage": "callback",
                "status": "failed",
            },
        )
        visible_message = showerror.call_args.args[1]
        self.assertIn("RT-ABCDEF1234", visible_message)
        self.assertNotIn("private-value", visible_message)

    def test_error_dialog_says_when_no_diagnostic_record_was_written(
        self,
    ) -> None:
        app = _bare_app()
        app.diagnostics.available = False

        with mock.patch.object(windows_app.messagebox, "showerror") as showerror:
            app._report_callback_exception(
                RuntimeError,
                RuntimeError("private"),
                None,
            )

        visible_message = showerror.call_args.args[1]
        self.assertIn("diagnostics are unavailable", visible_message)
        self.assertIn("no diagnostic record was written", visible_message)

    def test_about_tab_exposes_local_privacy_and_support_information(
        self,
    ) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        diagnostic_log = mock.Mock()
        diagnostic_log.available = True
        diagnostic_log.log_path = Path("C:/Rat-Trap/rat-trap.log")
        app = windows_app.RatTrapApp(
            root,
            diagnostic_log=diagnostic_log,
        )
        self.addCleanup(root.destroy)

        self.assertEqual(app.tabs.tab(app.about_tab, "text"), "About")
        visible_text = "\n".join(
            str(child.cget("text"))
            for child in app.about_tab.winfo_children()
            if "text" in child.keys()
        )
        self.assertIn("Privacy", visible_text)
        self.assertIn("no account", visible_text)
        self.assertIn("Support", visible_text)
        self.assertIn(windows_app.SUPPORT_EMAIL, visible_text)

        app._copy_support_details()
        self.assertIn(windows_app.APP_VERSION, root.clipboard_get())
        self.assertIn("%LOCALAPPDATA%", root.clipboard_get())
        self.assertNotIn(str(diagnostic_log.log_path), root.clipboard_get())

    def test_real_tk_loop_completes_background_task(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        root.withdraw()
        diagnostic_log = mock.Mock()
        diagnostic_log.available = True
        diagnostic_log.log_path = Path("C:/Rat-Trap/rat-trap.log")
        app = windows_app.RatTrapApp(
            root,
            diagnostic_log=diagnostic_log,
        )
        self.addCleanup(root.destroy)
        results = []

        app._run_task(
            "Creating archive...",
            lambda: "complete",
            lambda result: results.append(result),
        )
        deadline = time.monotonic() + 5
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)

        self.assertFalse(app.busy)
        self.assertEqual(results, ["complete"])
        self.assertEqual(app.status_text.get(), "Ready")


if __name__ == "__main__":
    unittest.main()
