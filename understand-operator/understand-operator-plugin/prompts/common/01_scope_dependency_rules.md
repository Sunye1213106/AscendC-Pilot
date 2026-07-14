# Scope Dependency Rules

Start from user paths, operator-name matches, registration entries, Host/Tiling entries, Kernel entries, API/Proto definitions, and Golden/Reference candidates.

Analyze C/C++ `#include`, Python `import` and `from ... import ...`, build/config/proto files, generated-code config, and architecture-selection config.

Repository dependencies discovered outside the operator directory enter candidate scope with discovery chain and reason. System headers and third-party packages are recorded but not source-read. Limit automatic dependency expansion to three layers; record deeper or unresolved items as uncertain.
