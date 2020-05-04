#!/bin/bash

function do_lcd {
    # LCD display driver
    wget https://github.com/waveshare/LCD-show/archive/master.zip
    unzip master.zip
    cd LCD-show-master
    sudo ./LCD7-800x480-show 180
    cd -
    # reboot will occur
}

function do_packages {
    # required packages
    sudo apt-get install -y \
        lightdm \
        xserver-xorg-video-fbturbo \
        x11-xserver-utils \
        fonts-freefont-ttf \
        python3-pygame \
        python3-evdev \
        python3-requests
    sudo mkdir -p /var/lib/lightdm/data
    sudo chown lightdm.lightdm /var/lib/lightdm/data
    sudo chmod 750 /var/lib/lightdm/data
}

function do_xsession {
    # startup for graphical session
    cat > ~/.xsession <<EOF
# adjust rights on LCD display backlight brightness controls
sudo chgrp video /sys/class/backlight/
sudo chgrp -R video /sys/devices/platform/rpi_backlight/
sudo chmod g+w /sys/class/backlight/rpi_backlight/brightness
# disable screensaver and display blanking
sudo /usr/bin/xset s off
sudo /usr/bin/xset -dpms
sudo /usr/bin/xset s noblank

cd projects/alarmclock-pi
while :
do
    python3 alarmclock.py
done
EOF
    chmod +x ~/.xsession
    # adjust rights on LCD display backlight brightness controls
    sudo chgrp video /sys/class/backlight/
    sudo chgrp -R video /sys/devices/platform/rpi_backlight/
    sudo chmod g+w /sys/class/backlight/rpi_backlight/brightness
}

task=$1
shift
do_$task $*
