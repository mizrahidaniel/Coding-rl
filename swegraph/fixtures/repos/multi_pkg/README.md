# multi_pkg

A 3-module fixture exercising a directed import chain ``a → b → c``. ``c`` is
the leaf; ``a`` is the public entry point. Used by the ``causal_hop`` task
family to test agents on bugs that live one or more import-hops away from
the failing test surface.
