(function () {
  const PRESETS = {
    "3Dプリンター・自作パーツ": [
      "制作物",
      "使用した道具・機材",
      "費用",
      "制作時間"
    ],
    "自転車用品・カスタマイズ": [
      "カスタマイズ内容",
      "費用",
      "作業時間"
    ],
    "メンテナンス": [
      "メンテナンス内容",
      "費用",
      "作業時間"
    ],
    "DIY": [
      "制作物",
      "使用した道具・機材",
      "使用した材料",
      "費用",
      "制作時間"
    ],
    "その他モノづくり": [
      "制作物",
      "使用した道具・機材",
      "使用した材料",
      "費用",
      "制作時間"
    ]
  };

  const h = window.h;
  const createClass = window.createClass;
  const toPlain = function (value) {
    if (!value) return {};
    if (typeof value.toJS === "function") return value.toJS();
    if (typeof value.toJSON === "function") return value.toJSON();
    return value;
  };

  const normalize = function (value) {
    const data = toPlain(value);
    return {
      category: data.category || "",
      production_data: Array.isArray(data.production_data)
        ? data.production_data.map(function (item) {
            return {
              label: item.label || "",
              value: item.value || "",
              custom: !!item.custom
            };
          })
        : []
    };
  };

  const Control = createClass({
    handleCategoryChange: function (event) {
      const data = normalize(this.props.value);
      const category = event.target.value;

      // 自由項目は残し、標準項目だけ選択カテゴリーの内容に入れ替える
      const customFields = data.production_data.filter(function (item) {
        return item.custom;
      });

      const fields = (PRESETS[category] || []).map(function (label) {
        const existing = data.production_data.find(function (item) {
          return item.label === label && !item.custom;
        });

        return {
          label: label,
          value: existing ? existing.value : ""
        };
      });

      customFields.forEach(function (item) {
        fields.push(item);
      });

      this.props.onChange({
        category: category,
        production_data: fields
      });
    },
    handleValueChange: function (index, value) {
      const data = normalize(this.props.value);
      data.production_data[index].value = value;
      this.props.onChange(data);
    },

    handleLabelChange: function (index, value) {
      const data = normalize(this.props.value);
      data.production_data[index].label = value;
      data.production_data[index].custom = true;
      this.props.onChange(data);
    },

    addCustomField: function () {
      const data = normalize(this.props.value);
      data.production_data.push({
        label: "",
        value: "",
        custom: true
      });
      this.props.onChange(data);
    },

    removeCustomField: function (index) {
      const data = normalize(this.props.value);
      data.production_data.splice(index, 1);
      this.props.onChange(data);
    },

    render: function () {
      const data = normalize(this.props.value);
      const self = this;

      const categoryOptions = [
        h("option", { key: "", value: "" }, "カテゴリーを選択してください")
      ].concat(Object.keys(PRESETS).map(function (category) {
        return h("option", {
          key: category,
          value: category
        }, category);
      }));

      const rows = data.production_data.map(function (item, index) {
        const isCustom = !!item.custom;
        const labelIsPreset = Object.keys(PRESETS).some(function (category) {
          return PRESETS[category].indexOf(item.label) !== -1;
        });

        return h("div", {
          key: index,
          style: {
            border: "1px solid #ddd",
            borderRadius: "6px",
            padding: "12px",
            marginTop: "10px"
          }
        },
          h("div", {
            style: {
              fontWeight: "bold",
              marginBottom: "6px"
            }
          }, isCustom || !labelIsPreset ? "自由項目名" : item.label),

          isCustom || !labelIsPreset
            ? h("input", {
                type: "text",
                value: item.label,
                placeholder: "項目名",
                style: { width: "100%", marginBottom: "8px" },
                onChange: function (event) {
                  self.handleLabelChange(index, event.target.value);
                }
              })
            : null,

          h("input", {
            type: "text",
            value: item.value,
            placeholder: "内容を入力（空欄でも構いません）",
            style: { width: "100%" },
            onChange: function (event) {
              self.handleValueChange(index, event.target.value);
            }
          }),

          isCustom
            ? h("button", {
                type: "button",
                style: { marginTop: "8px" },
                onClick: function () {
                  self.removeCustomField(index);
                }
              }, "この自由項目を削除")
            : null
        );
      });

      return h("div", { className: this.props.classNameWrapper },
        h("label", {
          htmlFor: this.props.forID,
          style: { display: "block", fontWeight: "bold", marginBottom: "8px" }
        }, "カテゴリー"),

        h("select", {
          id: this.props.forID,
          value: data.category,
          style: { width: "100%", padding: "8px" },
          onChange: this.handleCategoryChange
        }, categoryOptions),

        h("p", {
          style: { color: "#666", fontSize: "12px", marginTop: "8px" }
        }, "カテゴリーを選択すると、推奨項目が追加されます。入力しない項目は空欄のままで構いません。"),

        h("div", { style: { marginTop: "18px" } },
          h("strong", {}, "制作・作業情報"),
          rows
        ),

        h("button", {
          type: "button",
          style: { marginTop: "14px" },
          onClick: this.addCustomField
        }, "＋ 自由項目を追加")
      );
    }
  });

  const Preview = createClass({
    render: function () {
      const data = normalize(this.props.value);

      return h("div", {},
        h("strong", {}, data.category || "カテゴリー未選択"),
        h("ul", {},
          data.production_data
            .filter(function (item) {
              return item.label || item.value;
            })
            .map(function (item, index) {
              return h("li", { key: index },
                item.label + "：" + item.value
              );
            })
        )
      );
    }
  });

  window.CMS.registerWidget("making_info", Control, Preview);
})();
