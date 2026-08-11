// SOURCE: cannbot-skills/ops/ascendc-code-review/references/cpp-general.md
explicit Foo(int x);          // good
explicit Foo(int x, int y=0); // good
Foo(int x, int y=0);          // bad
explicit Foo(int x, int y);   // bad
