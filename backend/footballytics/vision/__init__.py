"""Auto-eventing: recover match events and speed metrics from broadcast video, scored against ground truth.

The pipeline (see autoevent.py):

1. clip.py      run the simulator and cut a window of tracking + events (the answer key)
2. render.py    render that window as broadcast video with the app's own 3D renderer (Playwright, headless)
3. detect.py    a pretrained COCO detector finds players and the ball in every frame
4. track.py     image -> pitch coordinates (camera calibration), tracking, team colours
5. events.py    possession, passes, player / ball / shot speeds, threshold flags - from the tracks alone
6. evaluate.py  compare with the simulator's ground truth: detection, positions, passes, speeds
"""
