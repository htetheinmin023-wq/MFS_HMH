[app]

title = MFS HMH
package.name = mfshmh
package.domain = org.mfshmh
version = 1.0

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,xml

# numpy/opencv intentionally NOT included: p4a master builds Python 3.14
# host + numpy 2.3.0 has no cp314 wheels -> source compile fails
# (known broken combo). The app degrades gracefully to the verified
# PIL fallbacks when cv2 is unavailable.
requirements = python3,kivy,pillow

orientation = portrait
fullscreen = 0

android.api = 35
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.sdk = 35
android.accept_sdk_license = True
android.archs = arm64-v8a
android.permissions = INTERNET

[buildozer]

log_level = 2
warn_on_root = 1
