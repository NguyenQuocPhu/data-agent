class DummyAgent:

    def __init__(self):
        self.score = 10

    def compute_fitness(self):
        return self.score * 1.5

    def do_not_touch_this(self):
        print('I should remain untouched!')