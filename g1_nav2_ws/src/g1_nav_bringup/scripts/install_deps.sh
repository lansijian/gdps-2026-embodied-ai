#!/usr/bin/env bash
# Reference: unitreerobotics/unitree_ros2 README (Foxy Cyclone build);
# Livox-SDK/Livox-SDK2 and livox_ros_driver2 build instructions.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
CI_MODE=${1:-}

# First deployment operation: preserve the robot's working network configuration.
if [[ "$CI_MODE" != --ci ]]; then
  OLD=${G1_OLD_WORKSPACE:-$HOME/g1_mid360_foxy_ws_stage3_20261020}
  if [[ -n "${MID360_CONFIG_SOURCE:-}" ]]; then
    INPUT=$MID360_CONFIG_SOURCE
  else
    mapfile -t FOUND < <(find "$OLD" -type f -name MID360_config.json | sort)
    if [[ ${#FOUND[@]} -eq 0 ]]; then
      printf 'No MID360_config.json under %s. Set MID360_CONFIG_SOURCE to the working file.\n' "$OLD" >&2
      exit 1
    fi
    INPUT=${FOUND[0]}
    for candidate in "${FOUND[@]}"; do
      if ! cmp -s -- "$INPUT" "$candidate"; then
      printf 'Found %s MID360_config.json files in %s. Set MID360_CONFIG_SOURCE to the actual working file.\n' "${#FOUND[@]}" "$OLD" >&2
      printf '%s\n' "${FOUND[@]}" >&2
      exit 1
      fi
    done
  fi
  cp -- "$INPUT" "$ROOT/src/g1_nav_bringup/config/mid360_config.json"
  cmp -- "$INPUT" "$ROOT/src/g1_nav_bringup/config/mid360_config.json"
  sha256sum "$INPUT" "$ROOT/src/g1_nav_bringup/config/mid360_config.json"
fi

SUDO=()
if [[ $EUID -ne 0 ]]; then SUDO=(sudo); fi
export DEBIAN_FRONTEND=noninteractive
"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y git cmake build-essential pkg-config libssl-dev libasio-dev \
  libtinyxml2-dev libpcl-dev python3-pip python3-colcon-common-extensions python3-rosdep \
  ros-foxy-navigation2 ros-foxy-nav2-bringup ros-foxy-slam-toolbox \
  ros-foxy-pointcloud-to-laserscan ros-foxy-rmw-cyclonedds-cpp ros-foxy-sensor-msgs-py \
  ros-foxy-pcl-conversions ros-foxy-rviz2
if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  "${SUDO[@]}" rosdep init
fi
rosdep update --rosdistro foxy --include-eol-distros
# SDK is already installed on G1 and is never imported by the default dry run.
# Livox has no Foxy apt package; it is compiled below from the official sources.
rosdep install --from-paths "$ROOT/src" --ignore-src -y --rosdistro foxy \
  --skip-keys 'unitree_sdk2py livox_ros_driver2'

fetch() {
  local repository=$1 revision=$2 destination=$3
  if [[ ! -d "$destination/.git" ]]; then
    mkdir -p "$destination"
    git -C "$destination" init -q
    git -C "$destination" remote add origin "https://github.com/$repository.git"
    git -C "$destination" fetch --depth 1 origin "$revision"
    git -C "$destination" checkout -q --detach FETCH_HEAD
  fi
  test "$(git -C "$destination" rev-parse HEAD)" = "$revision"
}
DEPS=$ROOT/.deps
fetch eclipse-cyclonedds/cyclonedds 9995905bce6c4cf9f740d6438bbf7fcfd1c83dfd "$DEPS/dds/src/cyclonedds"
fetch ros2/rmw_cyclonedds c12abc56983204f1d91f2d839d394528c7b29b42 "$DEPS/dds/src/rmw_cyclonedds"
(
  cd "$DEPS/dds"
  colcon build --packages-select cyclonedds --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release
  set +u
  source /opt/ros/foxy/setup.bash
  source install/setup.bash
  set -u
  colcon build --packages-select rmw_cyclonedds_cpp --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release
)

fetch Livox-SDK/Livox-SDK2 c0796f04c143143899c87a773d9f6b7136453c0b "$DEPS/Livox-SDK2"
cmake -S "$DEPS/Livox-SDK2" -B "$DEPS/Livox-SDK2/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$DEPS/livox-sdk"
cmake --build "$DEPS/Livox-SDK2/build" --parallel 2
cmake --install "$DEPS/Livox-SDK2/build"
fetch Livox-SDK/livox_ros_driver2 21445540f0d100dc86a7e6df312dd70bbdb4afdf "$DEPS/livox/src/livox_ros_driver2"
cp "$DEPS/livox/src/livox_ros_driver2/package_ROS2.xml" "$DEPS/livox/src/livox_ros_driver2/package.xml"
cp -r "$DEPS/livox/src/livox_ros_driver2/launch_ROS2" "$DEPS/livox/src/livox_ros_driver2/launch"
(
  set +u
  source /opt/ros/foxy/setup.bash
  source "$DEPS/dds/install/setup.bash"
  set -u
  cd "$DEPS/livox"
  colcon build --cmake-args -DROS_EDITION=ROS2 -DDISTRO_ROS=foxy -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="$DEPS/livox-sdk;$CMAKE_PREFIX_PATH" \
    -DLIVOX_LIDAR_SDK_LIBRARY="$DEPS/livox-sdk/lib/liblivox_lidar_sdk_shared.so" \
    -DLIVOX_LIDAR_SDK_INCLUDE_DIR="$DEPS/livox-sdk/include"
)
cat > "$DEPS/environment.bash" <<'ENV'
# Reference: ROS 2 workspace overlay setup; source this file before colcon or launch.
_g1_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source /opt/ros/foxy/setup.bash
source "$_g1_root/.deps/dds/install/setup.bash"
source "$_g1_root/.deps/livox/install/setup.bash"
export LD_LIBRARY_PATH="$_g1_root/.deps/livox-sdk/lib:${LD_LIBRARY_PATH:-}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset _g1_root
ENV
echo "Dependencies built. Source $DEPS/environment.bash, then colcon build --symlink-install."
