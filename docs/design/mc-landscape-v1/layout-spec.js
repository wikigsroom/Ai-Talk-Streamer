window.MC_LAYOUT = {
  "schema_version": 1,
  "id": "mc-landscape-v1",
  "revision": 4,
  "branch": "mc",
  "classification": "FROZEN_DESIGN_BASELINE",
  "runtime_implemented": false,
  "canvas": {
    "width": 1920,
    "height": 1080,
    "aspect_ratio": "16:9"
  },
  "avatar_stream": {
    "width": 720,
    "height": 1280,
    "fps": 25,
    "fit": "explicit_preview_crop",
    "new_inference_required_for_static_preview": false,
    "new_materials_status": "PLANNED_NOT_GENERATED"
  },
  "avatar_reference": {
    "width": 720,
    "height": 1280,
    "unchanged_file": true,
    "kind": "static_legacy_reference"
  },
  "avatar_default": "circle",
  "avatar_variants": {
    "circle": {
      "region": {
        "x": 1624,
        "y": 732,
        "width": 264,
        "height": 264
      },
      "status_region": {
        "x": 1624,
        "y": 1032,
        "width": 264,
        "height": 24
      },
      "mask": "circle",
      "preview_crop": {
        "x": 80,
        "y": 215,
        "width": 560,
        "height": 560
      },
      "media_area_percent": 2.64,
      "planned_material": {
        "master": [
          720,
          720
        ],
        "candidate_inference": [
          640,
          640
        ],
        "fps": 25,
        "status": "NOT_GENERATED_NOT_BENCHMARKED"
      }
    },
    "landscape": {
      "region": {
        "x": 1568,
        "y": 816,
        "width": 320,
        "height": 180
      },
      "status_region": {
        "x": 1568,
        "y": 1032,
        "width": 320,
        "height": 24
      },
      "mask": "rounded_rectangle",
      "preview_crop": {
        "x": 0,
        "y": 230,
        "width": 720,
        "height": 405
      },
      "media_area_percent": 2.778,
      "planned_material": {
        "master": [
          1280,
          720
        ],
        "candidate_inference": [
          960,
          540
        ],
        "fps": 25,
        "status": "NOT_GENERATED_NOT_BENCHMARKED"
      }
    }
  },
  "regions": {
    "header": {
      "x": 32,
      "y": 24,
      "width": 1856,
      "height": 56
    },
    "game": {
      "x": 0,
      "y": 0,
      "width": 1920,
      "height": 1080
    },
    "danmaku": {
      "x": 32,
      "y": 108,
      "width": 1856,
      "height": 104
    },
    "chat": {
      "x": 1480,
      "y": 136,
      "width": 408,
      "height": 480
    },
    "gift": {
      "x": 1480,
      "y": 632,
      "width": 408,
      "height": 56
    },
    "avatar": {
      "x": 1624,
      "y": 732,
      "width": 264,
      "height": 264
    },
    "caption": {
      "x": 320,
      "y": 840,
      "width": 1120,
      "height": 84
    },
    "status": {
      "x": 1624,
      "y": 1032,
      "width": 264,
      "height": 24
    }
  },
  "protected_game_regions": {
    "crosshair": {
      "x": 800,
      "y": 380,
      "width": 320,
      "height": 320
    },
    "native_bottom_hud": {
      "x": 480,
      "y": 936,
      "width": 960,
      "height": 144
    },
    "native_top_bossbar": {
      "x": 576,
      "y": 0,
      "width": 768,
      "height": 92
    }
  },
  "danmaku": {
    "direction": "right_to_left",
    "lanes": 2,
    "lane_pitch_px": 52,
    "speed_px_per_second": 140,
    "gap_px": 52,
    "max_visible": 6,
    "pending_limit": 24,
    "pending_ttl_ms": 20000,
    "max_text_characters": 28,
    "max_nickname_characters": 8,
    "reduced_motion": "pause_in_place",
    "selected_comment_card": false
  },
  "chat": {
    "default_mode": "feed",
    "direction": "bottom_to_top",
    "max_visible": 4,
    "row_height_px": 100,
    "row_gap_px": 10,
    "minimum_interval_ms": 1000,
    "transition_ms": 320,
    "pending_limit": 24,
    "pending_ttl_ms": 20000,
    "display_ttl_ms": 24000,
    "max_text_characters": 32,
    "max_nickname_characters": 10,
    "selected_comment_card": false,
    "simultaneous_feed_and_fly": false,
    "role_metadata": "trusted_server_fields_only; demo badges are fictional fixtures",
    "style_reference": "https://github.com/xfgryujk/blivechat/wiki/自定义CSS参考",
    "default_side": "right",
    "side_presets": {
      "right": {
        "chat": {
          "x": 1480,
          "y": 136,
          "width": 408,
          "height": 480
        },
        "gift": {
          "x": 1480,
          "y": 632,
          "width": 408,
          "height": 56
        }
      },
      "left": {
        "chat": {
          "x": 32,
          "y": 136,
          "width": 408,
          "height": 480
        },
        "gift": {
          "x": 32,
          "y": 632,
          "width": 408,
          "height": 56
        }
      }
    },
    "side_change": "instant_reposition_preserve_nodes_queue_and_elapsed_time",
    "flying_mode_side_behavior": "remember_feed_side; flying_lanes_and_direction_unchanged"
  },
  "gift": {
    "max_visible": 1,
    "seconds": 7,
    "extra_audio": false,
    "demo_only": true
  },
  "layer_order": [
    "game",
    "failure_cover",
    "header",
    "chat_or_danmaku",
    "gift",
    "caption",
    "avatar",
    "status",
    "review_guides"
  ],
  "composition": {
    "game_source": "full_canvas_native_capture",
    "programme_overlay": "transparent_full_canvas",
    "global_opaque_backplate": false
  },
  "comparison_to_previous_design": {
    "game_previous_size": [
      1472,
      828
    ],
    "game_base_area_increase_percent": 70.13,
    "revision_2_avatar_size": [
      216,
      384
    ],
    "revision_2_avatar_area_percent": 4,
    "circle_media_area_reduction_from_revision_2_percent": 34,
    "landscape_media_area_reduction_from_revision_2_percent": 30.56,
    "media_area_excludes_nameplate_border_shadow": true
  },
  "palette": {
    "window": "#E8EFF4",
    "paper": "#F8FBFC",
    "ink": "#263D4B",
    "blue": "#7898B7",
    "leaf": "#547B60",
    "wood": "#B38964"
  },
  "typography": {
    "title": "KaiTi, STKaiti, serif",
    "body": "Microsoft YaHei UI, Microsoft YaHei, sans-serif",
    "numbers": "Bahnschrift, Consolas, sans-serif"
  },
  "scenes": [
    "play",
    "interact",
    "break",
    "recover"
  ],
  "scene_transition_changes_game_control": false,
  "unique_avatar_playback_authorities_in_prototype": 0,
  "unique_avatar_playback_authorities_in_planned_runtime": 1,
  "output_fps": {
    "preferred_if_supported": 25,
    "encoder_fallback_if_required": 30,
    "avatar_unique_frames_per_second": 25,
    "validated": false
  },
  "source_reference_sha256": "451647d9598a067de868af9113a719b965b55d6594202396a6c5a9b6f9bdbcab",
  "image_fixture": "Original local SVG illustration; no actual game connection or measurements",
  "version": "1.0.0",
  "status": "DESIGN_FROZEN",
  "frozen_on": "2026-10-29",
  "canonical_source": "configs/layouts/mc-landscape-v1.json",
  "backend_position_control": {
    "setting": "overlay.mc_chat_side",
    "values": [
      "left",
      "right"
    ],
    "default": "right",
    "endpoint": "/api/dsh/room/config",
    "persisted": true,
    "realtime_channel": "existing_room_state_sse",
    "implementation": "source_implemented_not_deployed",
    "affects": [
      "chat",
      "gift"
    ],
    "does_not_reset_messages": true
  },
  "freeze_scope": {
    "fixed": [
      "full_canvas_game",
      "avatar_default_and_regions",
      "caption_and_hud_protection",
      "palette",
      "single_playback_authority",
      "no_selected_comment_card"
    ],
    "configurable": [
      "overlay.mc_chat_side"
    ],
    "alternatives": [
      "landscape_avatar",
      "flying_comments"
    ],
    "new_media_and_mc_runtime_accepted": false
  }
};
