"""State-machine regression tests; no user desktop interaction."""
import unittest
import queue
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop_todo import dockguard as d


class LayersTest(unittest.TestCase):
    def setUp(self):
        self.native = Mock()
        self.native.GetForegroundWindow.return_value = 30
        self.native.GetWindow.return_value = 0
        self.native_patch = patch.object(d, '_u', self.native, create=True)
        self.native_patch.start()
        self.addCleanup(self.native_patch.stop)
        self.root = Mock()
        self.guard = d.DesktopGuard(SimpleNamespace(root=self.root))
        self.guard._running = True
        self.guard._foreground = 30
        self.guard._handles = Mock(return_value=[10, 11])
        self.guard._apply = Mock()

    def test_idle_and_pointer_movement_do_not_raise(self):
        for _ in range(5):
            self.guard._poll()
        self.assertFalse(self.guard._raised)

    def test_click_raises_and_pointer_leaving_does_not_sink(self):
        self.guard._events.put(10)
        self.guard._poll()
        self.guard._poll()
        self.assertTrue(self.guard._raised)
        self.guard._apply.assert_called_with([10, 11])

    def test_external_click_sinks_even_without_foreground_change(self):
        self.guard._raised = True
        self.guard._events.put(99)
        self.guard._poll()
        self.assertFalse(self.guard._raised)

    def test_popup_click_is_inside(self):
        self.guard._events.put(11)
        self.guard._poll()
        self.assertTrue(self.guard._raised)

    def test_owned_native_dialog_is_inside(self):
        self.native.GetWindow.side_effect = lambda h, _: {12: 11}.get(h, 0)
        self.guard._events.put(12)
        self.guard._poll()
        self.assertTrue(self.guard._raised)

    def test_fast_clicks_keep_the_last_click(self):
        for hit in (10, 99, 11, 99):
            self.guard._events.put(hit)
        self.guard._poll()
        self.assertFalse(self.guard._raised)

    def test_alt_tab_sinks(self):
        self.guard._raised = True
        self.native.GetForegroundWindow.return_value = 99
        self.guard._poll()
        self.assertFalse(self.guard._raised)

    def test_pinned_mode_survives_external_click_and_alt_tab(self):
        self.guard.set_always_on_top(True)
        self.guard._events.put(99)
        self.guard._poll()
        self.assertTrue(self.guard._raised)
        self.native.GetForegroundWindow.return_value = 100
        self.guard._poll()
        self.assertTrue(self.guard._raised)

    def test_disabling_pinned_mode_docks_immediately(self):
        self.guard.set_always_on_top(True)
        self.guard._events.put(10)
        self.guard.set_always_on_top(False)
        self.assertFalse(self.guard._raised)
        self.assertTrue(self.guard._events.empty())
        self.guard._apply.assert_called_with([10, 11])

    def test_saved_pin_setting_is_loaded(self):
        guard = d.DesktopGuard(SimpleNamespace(topmost=True))
        self.assertTrue(guard._always_on_top)

    def test_foreground_switch_to_popup_keeps_raised(self):
        self.guard._raised = True
        self.native.GetForegroundWindow.return_value = 11
        self.guard._poll()
        self.assertTrue(self.guard._raised)

    def test_insert_above_desktop_uses_predecessor(self):
        self.native.GetWindow.return_value = 25
        with patch.object(d, '_get_long', return_value=0, create=True), \
                patch.object(d, '_position') as move:
            d._insert_above(10, 40)
        move.assert_called_once_with(10, 25)

    def test_already_docked_does_not_restack(self):
        self.native.GetWindow.return_value = 10
        with patch.object(d, '_position') as move:
            d._insert_above(10, 40)
        move.assert_not_called()

    def test_topmost_predecessor_must_not_promote_docked_window(self):
        self.native.GetWindow.return_value = 25
        with patch.object(d, '_get_long', return_value=8, create=True), \
                patch.object(d, '_position') as move:
            d._insert_above(10, 40)
        move.assert_called_once_with(10, d.TOP)

    def test_explorer_missing_does_not_sink_below_wallpaper(self):
        self.native.GetShellWindow.return_value = 0
        self.assertIsNone(d._desktop_anchor([10, 11]))

    def test_hidden_root_still_included_for_recovery(self):
        self.root.winfo_ismapped.return_value = False
        self.native.GetAncestor.return_value = 10
        app = SimpleNamespace(root=self.root, settings_win=None,
                              _add_win=None, _font_picker=None)
        self.assertEqual(d.DesktopGuard(app)._handles(), [10])

    def test_covered_click_raises_and_explicitly_activates(self):
        self.guard._events.put((10, True))
        with patch.object(d, '_position') as move:
            self.guard._poll()
        move.assert_called_once_with(10, d.TOPMOST)
        self.assertTrue(self.guard._raised)
        self.native.SetForegroundWindow.assert_called_once_with(10)

    def test_later_outside_click_cancels_pending_activation(self):
        self.guard._events.put((10, True))
        self.guard._events.put(99)
        self.guard._poll()
        self.assertFalse(self.guard._raised)
        self.native.SetForegroundWindow.assert_not_called()

    def test_covered_click_consumes_press_and_matching_release_only(self):
        events = queue.SimpleQueue()
        watcher = d._MouseWatcher(events, [10])
        info = SimpleNamespace(pt=d.W.POINT(5, 5), mouseData=0)
        self.native.GetAncestor.return_value = 10
        with patch.object(d, '_covered', return_value=True):
            self.assertTrue(watcher._click(0x0201, info))
            self.assertFalse(watcher._click(0x0205, info))
            self.assertTrue(watcher._click(0x0202, info))
            self.assertFalse(watcher._click(0x0202, info))
        self.assertEqual(events.get(), (10, True))

    def test_uncovered_click_is_not_consumed(self):
        watcher = d._MouseWatcher(queue.SimpleQueue(), [10])
        self.native.GetAncestor.return_value = 10
        with patch.object(d, '_covered', return_value=False):
            self.assertFalse(watcher._click(
                0x0201, SimpleNamespace(pt=d.W.POINT(), mouseData=0)))

    def test_foreign_application_click_is_never_consumed(self):
        watcher = d._MouseWatcher(queue.SimpleQueue(), [10])
        self.native.GetAncestor.return_value = 99
        with patch.object(d, '_covered') as covered:
            self.assertFalse(watcher._click(
                0x0201, SimpleNamespace(pt=d.W.POINT(), mouseData=0)))
        covered.assert_not_called()

    def test_peek_uses_exclusion_not_disallow_preview(self):
        dwm = Mock()
        dwm.DwmSetWindowAttribute.return_value = 0
        with patch.object(d, '_dwm', dwm, create=True):
            self.guard._exclude_from_peek(10)
        self.assertEqual(dwm.DwmSetWindowAttribute.call_args.args[:2], (10, 12))
        dwm.DwmGetWindowAttribute.assert_not_called()

    def test_coverage_skips_own_minimized_and_cloaked_windows(self):
        dwm = Mock()
        def attribute(hwnd, attr, output, size):
            output._obj.value = int(hwnd == 24)
            return 0
        dwm.DwmGetWindowAttribute.side_effect = attribute
        self.native.IsWindowVisible.return_value = True
        self.native.IsIconic.side_effect = lambda hwnd: hwnd == 23
        rect = d.W.RECT(0, 0, 100, 100)
        with patch.object(d, '_dwm', dwm, create=True), \
                patch.object(d, '_windows', return_value=[11, 23, 24, 10]), \
                patch.object(d, '_class_of', return_value='Application'), \
                patch.object(d, '_frame', return_value=rect):
            self.assertFalse(d._covered(10, (10, 11)))

    def test_coverage_requires_real_rectangle_overlap(self):
        self.assertFalse(d._overlaps(d.W.RECT(0, 0, 10, 10),
                                     d.W.RECT(10, 0, 20, 10)))
        self.assertTrue(d._overlaps(d.W.RECT(0, 0, 10, 10),
                                    d.W.RECT(9, 0, 20, 10)))


if __name__ == '__main__':
    unittest.main()
