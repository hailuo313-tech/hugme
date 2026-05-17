export type CharacterProfileFieldKey =
  | "age"
  | "birthplace"
  | "current_city"
  | "height"
  | "body_type"
  | "face_style"
  | "clothing_style"
  | "distinctive_feature"
  | "occupation"
  | "education"
  | "daily_rhythm"
  | "living_situation"
  | "hobby"
  | "family_origin"
  | "sibling_position"
  | "family_relationship"
  | "childhood_background"
  | "relationship_status"
  | "attachment_style"
  | "temperament"
  | "emotional_expression"
  | "humor_style"
  | "core_value"
  | "worldview"
  | "money_attitude"
  | "life_goal"
  | "social_style"
  | "weekend_activity"
  | "favorite_topic"
  | "stress_response";

export interface CharacterProfileOption {
  value: string;
  label: string;
}

export interface CharacterProfileField {
  key: CharacterProfileFieldKey;
  label: string;
  hint: string;
  options: CharacterProfileOption[];
}

export interface CharacterProfileGroup {
  title: string;
  description: string;
  fields: CharacterProfileField[];
}

function options(values: string[]): CharacterProfileOption[] {
  if (values.length !== 10) {
    throw new Error("Each character profile field must define exactly 10 options.");
  }
  return values.map((value) => ({ value, label: value }));
}

export const CHARACTER_PROFILE_GROUPS: CharacterProfileGroup[] = [
  {
    title: "基本身份",
    description: "回答年龄、出生地、城市等用户最常问的基础问题。",
    fields: [
      {
        key: "age",
        label: "年龄",
        hint: "用于直接回答“你几岁”。",
        options: options(["21", "22", "23", "24", "25", "26", "27", "28", "30", "32"]),
      },
      {
        key: "birthplace",
        label: "出生地",
        hint: "保持具体但不过度暴露地址。",
        options: options(["杭州", "上海", "成都", "广州", "深圳", "南京", "厦门", "青岛", "台北", "首尔"]),
      },
      {
        key: "current_city",
        label: "现居城市",
        hint: "可与出生地不同，增加真实感。",
        options: options(["上海", "北京", "杭州", "成都", "深圳", "广州", "南京", "苏州", "东京", "新加坡"]),
      },
    ],
  },
  {
    title: "职业与生活",
    description: "塑造角色白天在做什么、如何生活。",
    fields: [
      {
        key: "occupation",
        label: "职业",
        hint: "会同步填充 legacy occupation。",
        options: options(["插画师", "咖啡店店长", "心理学研究助理", "产品设计师", "自由摄影师", "花艺师", "瑜伽教练", "音乐老师", "内容编辑", "宠物护理师"]),
      },
      {
        key: "education",
        label: "教育背景",
        hint: "用于回答校园、专业经历。",
        options: options(["心理学本科", "视觉传达本科", "音乐学院毕业", "文学硕士", "社会学本科", "护理学本科", "商科本科", "电影学院毕业", "设计硕士", "自学成才"]),
      },
      {
        key: "daily_rhythm",
        label: "作息节奏",
        hint: "影响日常陪聊的时间感。",
        options: options(["早睡早起", "夜猫子", "午后效率最高", "工作日规律", "周末慢节奏", "晨跑型", "下午茶型", "深夜创作型", "弹性自由职业", "轮班作息"]),
      },
      {
        key: "living_situation",
        label: "居住状态",
        hint: "避免具体门牌，表达生活氛围即可。",
        options: options(["独居小公寓", "和猫一起住", "与室友合租", "住在工作室附近", "住在老城区", "住在海边城市", "住在安静社区", "和姐姐同住", "短租旅行中", "住在学校附近"]),
      },
      {
        key: "hobby",
        label: "爱好",
        hint: "常被用户问到，Prompt 会直接使用。",
        options: options(["看展和夜跑", "烘焙和手冲咖啡", "爵士乐和黑胶", "读小说和写手帐", "爬山和拍照", "养猫和做饭", "瑜伽和冥想", "电影和城市散步", "花艺和香薰", "游戏和轻小说"]),
      },
    ],
  },
  {
    title: "家庭背景",
    description: "提供不狗血但可共情的成长线索。",
    fields: [
      {
        key: "family_origin",
        label: "家庭出身",
        hint: "会用于 legacy background。",
        options: options(["普通城市家庭", "小城教师家庭", "单亲但稳定", "医生家庭", "自由职业家庭", "传统大家庭", "海外生活过", "沿海商贩家庭", "文艺家庭", "工薪家庭"]),
      },
      {
        key: "sibling_position",
        label: "手足位置",
        hint: "影响照顾感和边界感。",
        options: options(["独生女", "家中长女", "有一个哥哥", "有一个姐姐", "有一个弟弟", "有一个妹妹", "双胞胎之一", "三姐弟中间", "最小的孩子", "重组家庭姐姐"]),
      },
      {
        key: "family_relationship",
        label: "家庭关系",
        hint: "用于回应家庭话题。",
        options: options(["亲近但有边界", "和妈妈更亲", "和爸爸关系平淡", "家庭沟通温和", "家人较传统", "成年后更独立", "偶尔有压力", "互相关心少表达", "关系修复中", "家庭支持稳定"]),
      },
      {
        key: "childhood_background",
        label: "童年背景",
        hint: "可自然解释人格来源。",
        options: options(["从小喜欢观察人", "小时候常搬家", "童年比较安静", "很早学会照顾人", "在海边长大", "常去外婆家", "参加过合唱团", "喜欢图书馆", "经历过转学", "家里常养宠物"]),
      },
    ],
  },
  {
    title: "外貌特征",
    description: "回答身高、穿搭、气质等低风险角色事实。",
    fields: [
      {
        key: "height",
        label: "身高",
        hint: "用于直接回答“你多高”。",
        options: options(["158cm", "162cm", "165cm", "168cm", "169cm", "170cm", "172cm", "175cm", "178cm", "180cm"]),
      },
      {
        key: "body_type",
        label: "体型",
        hint: "保持健康、非露骨描述。",
        options: options(["纤细", "匀称", "偏高挑", "运动感", "小只型", "柔和圆润", "清瘦", "健康结实", "肩颈线条好", "轻盈感"]),
      },
      {
        key: "face_style",
        label: "面部气质",
        hint: "避免过度性化。",
        options: options(["清冷温柔", "邻家亲切", "笑眼明显", "书卷气", "淡颜耐看", "明亮元气", "成熟知性", "安静柔和", "猫系灵动", "自然素净"]),
      },
      {
        key: "clothing_style",
        label: "穿衣风格",
        hint: "可用于日常闲聊。",
        options: options(["简约通勤", "法式复古", "日系清爽", "运动休闲", "温柔针织", "黑白极简", "文艺棉麻", "轻熟优雅", "宽松舒适", "户外机能"]),
      },
      {
        key: "distinctive_feature",
        label: "辨识特征",
        hint: "一个记忆点即可。",
        options: options(["左眼下有小痣", "说话会轻轻笑", "常戴银色耳钉", "喜欢低马尾", "总带帆布包", "手腕有红绳", "香水很淡", "指甲常是裸色", "常戴圆框眼镜", "笑起来有酒窝"]),
      },
    ],
  },
  {
    title: "性格与情感",
    description: "决定亲密度、回应方式和情绪表达。",
    fields: [
      {
        key: "relationship_status",
        label: "感情状态",
        hint: "会同步填充 relationship_position。",
        options: options(["没有男朋友", "单身", "暧昧中", "刚结束一段关系", "专注工作暂不恋爱", "慢热观察中", "不主动谈恋爱", "相信长期关系", "保持开放心态", "享受独处"]),
      },
      {
        key: "attachment_style",
        label: "依恋风格",
        hint: "用于边界和陪伴感。",
        options: options(["安全型", "慢热型", "回避但温柔", "需要稳定回应", "独立但重视陪伴", "容易心软", "谨慎信任", "表达克制", "亲密后很黏", "边界清晰"]),
      },
      {
        key: "temperament",
        label: "性格底色",
        hint: "与 tone 分数一起影响 Prompt。",
        options: options(["温柔稳定", "俏皮明亮", "安静敏感", "理性知性", "元气直率", "成熟包容", "轻微毒舌", "治愈耐心", "浪漫细腻", "松弛幽默"]),
      },
      {
        key: "emotional_expression",
        label: "情绪表达",
        hint: "决定是否直说感受。",
        options: options(["会直接说感受", "先听后说", "喜欢用比喻", "情绪来得慢", "会轻轻撒娇", "难过时安静", "开心会分享细节", "压力大时需要空间", "善于安慰别人", "不喜欢争吵"]),
      },
      {
        key: "humor_style",
        label: "幽默风格",
        hint: "配合 humor_score 使用。",
        options: options(["轻松吐槽", "冷幽默", "可爱自嘲", "温柔玩笑", "生活观察型", "反差萌", "文字梗", "笨拙真诚", "不常开玩笑", "机灵接话"]),
      },
    ],
  },
  {
    title: "价值观与世界观",
    description: "让角色在深聊时有一致的判断标准。",
    fields: [
      {
        key: "core_value",
        label: "核心价值观",
        hint: "用于人生话题。",
        options: options(["真诚比完美重要", "稳定关系需要边界", "温柔也要有力量", "先照顾好自己", "自由与责任并重", "长期主义", "尊重差异", "慢慢来也可以", "情绪值得被看见", "生活要有审美"]),
      },
      {
        key: "worldview",
        label: "世界观",
        hint: "避免政治宗教立场。",
        options: options(["世界复杂但仍值得信任", "人会在关系中成长", "小事也能改变一天", "多数人都在努力生活", "保持好奇心", "经历会变成养分", "温和但不天真", "答案常在过程里", "不急着评判别人", "相信善意需要行动"]),
      },
      {
        key: "money_attitude",
        label: "金钱观",
        hint: "付费语境也要自然克制。",
        options: options(["量入为出", "愿意为体验花钱", "重视安全感", "不冲动消费", "喜欢记账", "钱是选择权", "重质量少而精", "会给自己小奖励", "投资学习", "不拿钱衡量爱"]),
      },
      {
        key: "life_goal",
        label: "人生目标",
        hint: "可用于鼓励用户。",
        options: options(["开一家小工作室", "做长期有温度的作品", "拥有稳定亲密关系", "环游几个海边城市", "写一本个人随笔", "帮助更多人变轻松", "保持身心健康", "拥有自己的花店", "学会更勇敢表达", "过简单但丰盛的生活"]),
      },
    ],
  },
  {
    title: "社交与日常习惯",
    description: "让角色的日常聊天更具体。",
    fields: [
      {
        key: "social_style",
        label: "社交风格",
        hint: "决定主动性和群体感。",
        options: options(["小圈子深交", "熟人面前话多", "慢热但靠谱", "喜欢一对一聊天", "群聊潜水", "主动照顾气氛", "社交后需要充电", "很会倾听", "不怕认识新人", "边界感强"]),
      },
      {
        key: "weekend_activity",
        label: "周末习惯",
        hint: "日常话题素材。",
        options: options(["逛展", "城市散步", "在家做饭", "去咖啡店看书", "爬山", "看电影", "整理房间", "上瑜伽课", "拍照探店", "陪猫晒太阳"]),
      },
      {
        key: "favorite_topic",
        label: "常聊话题",
        hint: "可作为破冰方向。",
        options: options(["音乐", "电影", "心理学", "猫狗", "旅行", "咖啡", "书和写作", "城市生活", "美食", "个人成长"]),
      },
      {
        key: "stress_response",
        label: "压力反应",
        hint: "用于共情但不诊断。",
        options: options(["先安静整理", "去散步", "写下来", "找朋友聊聊", "做饭放松", "听歌循环", "整理房间", "短暂逃避后处理", "深呼吸冥想", "睡一觉再说"]),
      },
    ],
  },
];

export const CHARACTER_PROFILE_FIELDS = CHARACTER_PROFILE_GROUPS.flatMap(
  (group) => group.fields
);
