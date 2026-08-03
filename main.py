from kivy.app import App
from kivy.uix.label import Label

class MFSApp(App):
    def build(self):
        return Label(text="MFS HMH v1.5")

if __name__ == "__main__":
    MFSApp().run()
