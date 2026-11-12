import 'dart:ui';
import 'package:flutter/material.dart';

class NowPlaying extends StatelessWidget {
  const NowPlaying({super.key});

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(20),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 30, sigmaY: 30),
        child: Container(
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.15),
            border: Border.all(color: Colors.white.withOpacity(0.25)),
          ),
          child: const Text('Now playing'),
        ),
      ),
    );
  }
}
