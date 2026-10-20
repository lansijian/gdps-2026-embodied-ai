#include <chrono>
#include <iomanip>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include "rclcpp/rclcpp.hpp"
#include "tf2_msgs/msg/tf_message.hpp"
#include "std_msgs/msg/string.hpp"

class Authority : public rclcpp::Node {
 public:
  Authority() : Node("g1_nav_tf_authority") {
    pub_ = create_publisher<std_msgs::msg::String>("/g1_nav/tf_authority", 10);
    auto cb = [this](tf2_msgs::msg::TFMessage::ConstSharedPtr msg,
                     const rclcpp::MessageInfo & info) {
      std::ostringstream out;
      const auto & gid = info.get_rmw_message_info().publisher_gid;
      for (auto byte : gid.data) out << std::hex << std::setw(2) << std::setfill('0') << int(byte);
      const auto id = out.str();
      for (const auto & t : msg->transforms) {
        const auto parent = t.header.frame_id, child = t.child_frame_id;
        const auto owner = std::make_pair(parent, id);
        if (edges_.count(child) && edges_[child] != owner) error_ = "TF_DUPLICATE_OWNER:" + child;
        if (parent.empty() || child.empty() || parent == child) error_ = "TF_INVALID_EDGE:" + child;
        edges_[child] = owner;
        std::set<std::string> seen;
        auto cursor = child;
        while (edges_.count(cursor)) {
          if (!seen.insert(cursor).second) { error_ = "TF_CYCLE:" + cursor; break; }
          cursor = edges_[cursor].first;
        }
      }
    };
    sub_ = create_subscription<tf2_msgs::msg::TFMessage>("/tf", rclcpp::QoS(100), cb);
    stat_ = create_subscription<tf2_msgs::msg::TFMessage>("/tf_static", rclcpp::QoS(100).transient_local(), cb);
    timer_ = create_wall_timer(std::chrono::milliseconds(100), [this]() {
      std_msgs::msg::String msg;
      msg.data = error_.empty() ? "OK" : error_;
      pub_->publish(msg);
    });
  }
 private:
  std::map<std::string, std::pair<std::string, std::string>> edges_;
  std::string error_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pub_;
  rclcpp::Subscription<tf2_msgs::msg::TFMessage>::SharedPtr sub_, stat_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<Authority>());
  rclcpp::shutdown();
  return 0;
}
