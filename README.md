# tucan3g-testbed

TUCAN3G is an european project that involves several organisms, mainly leaded by the Universidad Rey Juan Carlos. This project aims to provide a better network service (and so improve the underlying services) connecting multiple wireless networks (from mobile networks to WiFi or WiMAX ones). 

In order to accomplish its goal, TUCAN3G created an algorithm that was supposed to improve the overall QoS of a mixed network (with different kind of wireless technologies), by limiting the traffic coming into the network and sharing the network capacity between the different flows that use it, in real time. 

To demonstrate that this algorithm was effectively working well, the TUCAN3G team decided to implement a little testbed with only 2 ALIX boards, and emulating 2 HNBs connected to one of these boards. 

This repository stores the set of scripts (shell, python, config files...) needed to turn a couple of ALIX boards with voyage 0.10 GNU/Linux preinstalled into routers that adapt their QoS parameters to the available throughput, as defined by the TUCAN3G project.

## + info

For further information, please write directly to [hello@eyeseetea.com](mailto:hello@eyeseetea.com)
