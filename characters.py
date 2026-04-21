from enum import Enum
import random
class Character(Enum):
    MISAKI = "太刀"
    FS = "风水"
    NEKO = "猫猫"
    FENNY = "蒸蛋"
    UMI = "蓝海晴"
    QUEEN = "女王"
    AZUSA = "真梦梓"
    FOX = "小狐狸"
    MOLLY = "茉莉"
    RIN = "凛"
    BUNNY = "邦妮"
    UNCLE = "叔叔"
    QP = "旗袍"
    NU = "修女"
    PANDA = "熊猫"
    DORO = "多萝西"
    KOI = "鼠鼠"
    MI = "米米"
    NINJA = "忍者"
    MEGASU = "美甲师"
    SLIME = "史莱姆"
    MS = "摩西"
    VAM = "吸血鬼"
    JE = "吉尔"
    AE = "阿尔"
    MOTO = "摩托"
    MY = "墨影"
    PA = "老板娘"
    Z3000 = "垃圾桶"
    CH = "超天酱"
    CA = "糖糖"
    RING = "玲玲"
    @classmethod
    def get_random_character(cls):
        """获取随机角色"""
        return random.choice(list(cls))

class Map(Enum):
    TOWN = "水乡古镇"
    ALLEY = "幽魂暗巷"
    COLLAGE = "魔法学院"
    FOREST = "园林中庭"
    DREAM = "星趴·梦想号"
    CELE = "御魂庆典"
    DRAG = "龙宫游乐园"
    @classmethod
    def get_random_map(cls):
        """获取随机地图"""
        return random.choice(list(cls))

def get_character_team(num=4):
    """获取随机角色组"""
    return random.sample(list(Character), num)