import threading
import unittest
from unittest.mock import Mock

from run_all import supervise


class CombinedServiceTests(unittest.TestCase):
    def test_child_exit_stops_both_and_exits_nonzero(self):
        web=Mock();web.poll.return_value=None
        bot=Mock();bot.poll.return_value=1
        launch=Mock(side_effect=[web,bot]);stop=Mock()
        self.assertEqual(supervise([('web',['web']),('bot',['bot'])],launch=launch,stop=stop),1)
        self.assertEqual(launch.call_count,2)
        self.assertEqual([call.args[0] for call in stop.call_args_list],[bot,web])

    def test_shutdown_event_stops_children_cleanly(self):
        stopped=threading.Event();processes=[Mock(),Mock()]
        for process in processes:process.poll.return_value=None
        def launch(command,**kwargs):
            p=processes[0] if command==['web'] else processes[1]
            if command==['bot']:stopped.set()
            return p
        stop=Mock()
        self.assertEqual(supervise([('web',['web']),('bot',['bot'])],stopped,launch,stop),0)
        self.assertEqual(stop.call_count,2)

    def test_second_child_launch_failure_cleans_first(self):
        web=Mock();stop=Mock();launch=Mock(side_effect=[web,OSError('cannot launch')])
        with self.assertRaises(OSError):supervise([('web',['web']),('bot',['bot'])],launch=launch,stop=stop)
        stop.assert_called_once_with(web)


if __name__=='__main__':unittest.main()
