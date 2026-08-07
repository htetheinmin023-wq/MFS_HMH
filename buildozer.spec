[app]

title = MFS HMH
package.name = mfshmh
package.domain = org.mfshmh
version = 1.0

source.dir = .
requirements = python3,kivy,pillow

android.api = 33
android.minapi = 24
android.build_tools_version = 33.0.2
android.sdk_path = /data/data/com.termux/files/home/.buildozer/android/platform/android-sdk



[buildozer]

log_level = 2
warn_on_root = 1
android.environ = CFLAGS=-I/data/data/com.termux/files/usr/include,LDFLAGS=-L/data/data/com.termux/files/usr/lib
android.build_tools_version = 35.0.0

