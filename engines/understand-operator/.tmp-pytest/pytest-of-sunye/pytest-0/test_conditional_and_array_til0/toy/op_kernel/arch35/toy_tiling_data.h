
        class Child { public: int64_t values[8]; };
        template <bool Enabled>
        class Root {
        public:
          typename std::conditional<!Enabled, Child, std::nullptr_t>::type child;
        };
        