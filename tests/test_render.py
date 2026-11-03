from datetime import date
import unittest

from PIL import ImageChops

from git_runner.activity import demo_snapshot, derive_state
from git_runner.render import BG, FRAME_COUNT, frame, position


class RenderTests(unittest.TestCase):
    def test_seamless_loop_in_each_mode(self):
        for mode in ('rest', 'walk', 'run'):
            with self.subTest(mode=mode):
                snapshot = demo_snapshot(mode, date(2026, 11, 2))
                state = derive_state(snapshot)
                self.assertIsNone(ImageChops.difference(frame(snapshot, state, 0),
                    frame(snapshot, state, FRAME_COUNT)).getbbox())

    def test_only_character_is_visible_and_moves_around_canvas(self):
        snapshot = demo_snapshot('run', date(2026, 11, 2))
        state = derive_state(snapshot)
        boxes = []
        for index in (0, 60, 120, 180):
            image = frame(snapshot, state, index)
            self.assertEqual(image.size, (768, 768))
            background = image.copy()
            background.paste(BG, (0, 0, 768, 768))
            box = ImageChops.difference(image, background).getbbox()
            self.assertIsNotNone(box)
            self.assertLess(box[2] - box[0], 160)
            self.assertLess(box[3] - box[1], 190)
            self.assertGreater(box[0], 0)
            self.assertLess(box[2], 768)
            boxes.append(box)
        self.assertLess(boxes[3][0], boxes[1][0])
        self.assertLess(boxes[0][1], boxes[2][1])

    def test_lap_position_is_continuous(self):
        self.assertEqual(position(0), position(1))


if __name__ == '__main__':
    unittest.main()
