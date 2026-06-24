import time

import numpy as np


class FPSCounter:
    def __init__(self):
        current_time = time.time()
        self.start_time_for_display = current_time
        self.last_time = current_time
        self.display_period_s = 5
        self.time_between_calls = []
        self.elements_for_mean = 50

    def get_and_print_fps(self, print_fps=True):
        current_time = time.time()
        self.time_between_calls.append(1.0 / (current_time - self.last_time + 1e-9))
        if len(self.time_between_calls) > self.elements_for_mean:
            self.time_between_calls.pop(0)
        self.last_time = current_time
        frequency = np.mean(self.time_between_calls)
        if (current_time - self.start_time_for_display) > self.display_period_s and print_fps:
            print("Frequency: {}Hz".format(int(frequency)))
            self.start_time_for_display = current_time
        return frequency

    def getAndPrintFPS(self, print_fps=True):
        return self.get_and_print_fps(print_fps=print_fps)
